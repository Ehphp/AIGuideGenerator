"""Unit tests for timeline payload compression (apps/api/app/pipeline/timeline_compress.py).

Covers:
1. Normal timeline passes through unchanged when compression is disabled.
2. Large OCR is truncated to max_ocr_chars.
3. Empty frames are dropped when drop_empty_frames=True.
4. Frame events are uniformly sampled when max_frame_events is set.
5. OCR is stripped entirely when strip_ocr=True.
6. compress_for_guide and compress_for_classify use the right settings.
7. Pre-call token logging: estimated tokens < safe_budget after compression.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pipeline.timeline_compress import (
    compress_for_classify,
    compress_for_guide,
    compress_timeline,
    estimate_tokens,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(t: float, ocr: str = "", ui: str = "", has_els: bool = False) -> dict:
    ev: dict = {"kind": "frame", "t": t, "frame_key": f"frame_{t:.0f}"}
    if ocr:
        ev["ocr_text"] = ocr
    if ui:
        ev["ui_summary"] = ui
    if has_els:
        ev["visual_elements"] = [{"label": "btn", "type": "button"}]
    return ev


def _make_transcript(t: float, text: str = "hello") -> dict:
    return {"kind": "transcript", "t": t, "t_end": t + 1.5, "text": text}


def _big_ocr(chars: int = 1000) -> str:
    return "A" * chars


# ---------------------------------------------------------------------------
# Tests: compress_timeline
# ---------------------------------------------------------------------------


def test_transcript_events_always_kept():
    timeline = {
        "events": [
            _make_transcript(0),
            _make_transcript(5),
            _make_frame(2.5),  # empty → should be dropped
        ]
    }
    compressed, stats = compress_timeline(timeline, drop_empty_frames=True)
    transcript_events = [e for e in compressed["events"] if e["kind"] == "transcript"]
    assert len(transcript_events) == 2
    assert stats["frames_dropped"] == 1


def test_ocr_truncated_to_max_chars():
    long_ocr = _big_ocr(2000)
    timeline = {"events": [_make_frame(0.0, ocr=long_ocr)]}
    compressed, stats = compress_timeline(timeline, max_ocr_chars=300)
    frame_ev = compressed["events"][0]
    assert len(frame_ev["ocr_text"]) <= 301  # 300 + ellipsis char
    assert stats["ocr_truncated"] == 1


def test_short_ocr_not_truncated():
    short_ocr = "Hello world"
    timeline = {"events": [_make_frame(0.0, ocr=short_ocr)]}
    compressed, stats = compress_timeline(timeline, max_ocr_chars=300)
    frame_ev = compressed["events"][0]
    assert frame_ev["ocr_text"] == short_ocr
    assert stats["ocr_truncated"] == 0


def test_empty_frame_dropped():
    timeline = {"events": [_make_frame(0.0)]}  # no ocr, no ui, no els
    compressed, stats = compress_timeline(timeline, drop_empty_frames=True)
    assert len(compressed["events"]) == 0
    assert stats["frames_dropped"] == 1


def test_frame_with_visual_elements_not_dropped():
    timeline = {"events": [_make_frame(0.0, has_els=True)]}
    compressed, stats = compress_timeline(timeline, drop_empty_frames=True)
    assert len(compressed["events"]) == 1
    assert stats["frames_dropped"] == 0


def test_strip_ocr_removes_ocr_text():
    timeline = {"events": [_make_frame(0.0, ocr="important text", ui="some summary")]}
    compressed, _ = compress_timeline(timeline, strip_ocr=True)
    frame_ev = compressed["events"][0]
    assert "ocr_text" not in frame_ev
    assert frame_ev["ui_summary"] == "some summary"


def test_max_frame_events_samples_uniformly():
    # 100 frame events; cap to 10.
    frames = [_make_frame(float(i), ocr="x") for i in range(100)]
    timeline = {"events": frames}
    compressed, _ = compress_timeline(timeline, max_frame_events=10)
    frame_evs = [e for e in compressed["events"] if e["kind"] == "frame"]
    assert len(frame_evs) == 10


def test_max_frame_events_keeps_all_transcripts():
    transcripts = [_make_transcript(float(i)) for i in range(50)]
    frames = [_make_frame(float(i) + 0.5, ocr="x") for i in range(100)]
    timeline = {"events": transcripts + frames}
    compressed, _ = compress_timeline(timeline, max_frame_events=10)
    transcript_evs = [e for e in compressed["events"] if e["kind"] == "transcript"]
    assert len(transcript_evs) == 50


def test_original_not_mutated():
    original_ocr = _big_ocr(1000)
    timeline = {"events": [_make_frame(0.0, ocr=original_ocr)]}
    compress_timeline(timeline, max_ocr_chars=100)
    # Original must not be modified.
    assert timeline["events"][0]["ocr_text"] == original_ocr


def test_ps_important_text_prevents_frame_drop():
    """A frame with only ps_important_text (no ocr/ui/visual_elements) must not be dropped."""
    ev = {
        "kind": "frame",
        "t": 5.0,
        "frame_key": "frame_0005",
        "ps_important_text": ["Create repository", "Private"],
        "screen_type": "form_page",
        "screen_summary": "form_page | app=github_web | signals=[Create repository]",
    }
    timeline = {"events": [ev]}
    compressed, stats = compress_timeline(timeline, drop_empty_frames=True)
    assert stats["frames_dropped"] == 0
    assert len(compressed["events"]) == 1
    assert compressed["events"][0]["ps_important_text"] == ["Create repository", "Private"]


def test_ps_important_text_and_screen_type_preserved_through_compression():
    """screen_type, screen_summary, ps_important_text survive OCR truncation."""
    ev = {
        "kind": "frame",
        "t": 10.0,
        "frame_key": "frame_0010",
        "ocr_text": _big_ocr(2000),
        "ui_summary": "UI text: ...",
        "screen_type": "terminal",
        "screen_summary": "terminal | app=vscode | signals=[git, commit]",
        "ps_important_text": ["git", "commit", "-m", "'fix'"],
    }
    timeline = {"events": [ev]}
    compressed, stats = compress_timeline(timeline, max_ocr_chars=100)
    out = compressed["events"][0]
    assert out["screen_type"] == "terminal"
    assert out["screen_summary"] == "terminal | app=vscode | signals=[git, commit]"
    assert out["ps_important_text"] == ["git", "commit", "-m", "'fix'"]
    assert len(out["ocr_text"]) <= 101  # truncated


# ---------------------------------------------------------------------------
# Tests: preset functions
# ---------------------------------------------------------------------------

def _make_settings(*, compress=True, max_ocr=300, max_ui=200, max_frames=60):
    return SimpleNamespace(
        llm_payload_compress=compress,
        llm_compress_max_ocr_chars=max_ocr,
        llm_compress_max_ui_summary_chars=max_ui,
        llm_compress_classify_max_frame_events=max_frames,
    )


def test_compress_for_guide_truncates_ocr():
    timeline = {"events": [_make_frame(0.0, ocr=_big_ocr(2000))]}
    compressed, stats = compress_for_guide(timeline, settings=_make_settings())
    assert len(compressed["events"][0]["ocr_text"]) <= 301


def test_compress_for_guide_disabled():
    timeline = {"events": [_make_frame(0.0, ocr=_big_ocr(2000))]}
    compressed, stats = compress_for_guide(timeline, settings=_make_settings(compress=False))
    # Should be the exact same object when disabled.
    assert compressed is timeline


def test_compress_for_classify_strips_ocr_and_caps_frames():
    frames = [_make_frame(float(i), ocr=_big_ocr(500), ui="summary") for i in range(100)]
    timeline = {"events": frames}
    compressed, stats = compress_for_classify(timeline, settings=_make_settings(max_frames=60))
    frame_evs = [e for e in compressed["events"] if e["kind"] == "frame"]
    assert len(frame_evs) <= 60
    for ev in frame_evs:
        assert "ocr_text" not in ev


# ---------------------------------------------------------------------------
# Tests: token budget
# ---------------------------------------------------------------------------

def test_token_estimate_reasonable():
    # 4000 chars → ~1000 tokens
    text = "a" * 4000
    tokens = estimate_tokens(text)
    assert tokens == 1000


def test_compression_reduces_token_estimate_significantly():
    """After compression, estimated tokens should be well below 25000."""
    # Simulate a 379s recording: 76 frames × 2000-char OCR + 250 transcript segments
    events = []
    for i in range(76):
        events.append(_make_frame(float(i * 5), ocr=_big_ocr(2000), ui="some ui summary text"))
    for i in range(250):
        events.append(_make_transcript(float(i * 1.5), "click the button then navigate to settings"))
    timeline = {"events": events}

    compressed, _ = compress_for_guide(timeline, settings=_make_settings(max_ocr=300))
    compressed_str = str(compressed)
    est_tokens = estimate_tokens(compressed_str)
    # The compressed payload should be well under the 25k safe budget.
    assert est_tokens < 20000, f"Too many tokens after compression: {est_tokens}"

    # Verify the original was much larger.
    original_tokens = estimate_tokens(str(timeline))
    assert original_tokens > est_tokens * 2
