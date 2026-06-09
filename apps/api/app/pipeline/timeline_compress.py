"""Timeline payload compression for LLM calls.

The ``build_timeline`` artifact can grow very large for long recordings
(many frames × rich OCR + visual_elements). Sending it unmodified to
gpt-4o on a Tier-1 org (30 000 TPM) causes HTTP 429 errors because
``input_tokens + max_tokens > TPM_limit``.

This module provides a deterministic compressor that keeps all information
needed to generate a guide while reducing total token count.

Token estimation uses the rule-of-thumb ``len(text) / 4``, which is a
reasonable approximation for ASCII/Latin text (Unicode-dense text may be
slightly under-counted).

Two preset compression modes are exported:

* :func:`compress_for_guide`     — full events, truncated OCR (used by
  ``generate_guide`` and ``extract_actions``).
* :func:`compress_for_classify`  — sampled frames, stripped OCR, only
  ui_summary + actions (used by ``classify_content``).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4  # rough approximation


def estimate_tokens(text: str) -> int:
    """Approximate token count for a string (chars / 4)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _truncate(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, breaking at a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space] + "\u2026"
    return truncated + "\u2026"


def compress_timeline(
    timeline: dict,
    *,
    max_ocr_chars: int = 300,
    max_ui_summary_chars: int = 200,
    max_frame_events: int | None = None,
    drop_empty_frames: bool = True,
    strip_ocr: bool = False,
) -> tuple[dict, dict]:
    """Return ``(compressed_timeline, stats)`` without mutating *timeline*.

    Parameters
    ----------
    max_ocr_chars:
        Maximum ``ocr_text`` characters to retain per frame event.
    max_ui_summary_chars:
        Maximum ``ui_summary`` characters to retain per frame event.
    max_frame_events:
        If set, sample frame events uniformly to keep at most this many.
        Transcript events are always kept intact.
    drop_empty_frames:
        Drop frame events with no text, no ui_summary, no visual_elements,
        and no possible_actions (these add tokens without any signal).
    strip_ocr:
        Remove ``ocr_text`` entirely (keep only ``ui_summary`` and
        structured fields). Useful for classify_content where raw OCR is
        not needed.
    """
    events_in: list[dict] = timeline.get("events") or []
    events_out: list[dict] = []
    ocr_truncated = 0
    frames_dropped = 0

    for ev in events_in:
        if ev.get("kind") != "frame":
            # Transcript events: keep as-is.
            events_out.append(ev)
            continue

        ocr = ev.get("ocr_text") or ""
        ui = ev.get("ui_summary") or ""
        vis_els = ev.get("visual_elements") or []
        poss_acts = ev.get("possible_actions") or []
        ps_text = ev.get("ps_important_text") or []

        if drop_empty_frames and not ocr.strip() and not ui.strip() and not vis_els and not poss_acts and not ps_text:
            frames_dropped += 1
            continue

        new_ev = dict(ev)

        if strip_ocr:
            new_ev.pop("ocr_text", None)
        elif len(ocr) > max_ocr_chars:
            new_ev["ocr_text"] = _truncate(ocr, max_ocr_chars)
            ocr_truncated += 1

        if len(ui) > max_ui_summary_chars:
            new_ev["ui_summary"] = _truncate(ui, max_ui_summary_chars)

        events_out.append(new_ev)

    # Uniform frame sampling when a cap is requested.
    if max_frame_events is not None:
        transcript_evs = [e for e in events_out if e.get("kind") != "frame"]
        frame_evs = [e for e in events_out if e.get("kind") == "frame"]
        if len(frame_evs) > max_frame_events:
            step = len(frame_evs) / max_frame_events
            sampled = [frame_evs[round(i * step)] for i in range(max_frame_events)]
            events_out = sorted(
                transcript_evs + sampled,
                key=lambda e: (float(e.get("t", 0)), 0 if e.get("kind") == "frame" else 1),
            )

    compressed: dict = {**timeline, "events": events_out}
    stats: dict = {
        "events_in": len(events_in),
        "events_out": len(events_out),
        "ocr_truncated": ocr_truncated,
        "frames_dropped": frames_dropped,
    }
    return compressed, stats


def compress_for_guide(timeline: dict, *, settings) -> tuple[dict, dict]:
    """Compression preset for ``generate_guide`` and ``extract_actions``.

    Keeps all events (transcript + frames), truncates ``ocr_text`` and
    ``ui_summary``, drops empty frames.  Does NOT sample frames.
    """
    if not settings.llm_payload_compress:
        return timeline, {"compressed": False}
    return compress_timeline(
        timeline,
        max_ocr_chars=settings.llm_compress_max_ocr_chars,
        max_ui_summary_chars=settings.llm_compress_max_ui_summary_chars,
        drop_empty_frames=True,
        strip_ocr=False,
    )


def compress_for_classify(timeline: dict, *, settings) -> tuple[dict, dict]:
    """Compression preset for ``classify_content``.

    Strips raw OCR (not needed for type classification), caps frame events
    to ``settings.llm_compress_classify_max_frame_events``, keeps all
    transcript events.  Designed to keep the classification call well under
    10 000 tokens.
    """
    if not settings.llm_payload_compress:
        return timeline, {"compressed": False}
    return compress_timeline(
        timeline,
        max_ocr_chars=150,
        max_ui_summary_chars=120,
        max_frame_events=settings.llm_compress_classify_max_frame_events,
        drop_empty_frames=True,
        strip_ocr=True,
    )


def log_payload_stats(stage: str, original: dict, compressed: dict, stats: dict) -> None:
    """Emit an INFO log comparing the original vs. compressed timeline."""
    orig_json_chars = sum(len(str(e)) for e in (original.get("events") or []))
    comp_json_chars = sum(len(str(e)) for e in (compressed.get("events") or []))
    orig_tokens = estimate_tokens(str(original))
    comp_tokens = estimate_tokens(str(compressed))
    log.info(
        "%s timeline compression: events %d→%d, est_tokens %d→%d "
        "(ocr_truncated=%d frames_dropped=%d)",
        stage,
        stats.get("events_in", "?"),
        stats.get("events_out", "?"),
        orig_tokens,
        comp_tokens,
        stats.get("ocr_truncated", 0),
        stats.get("frames_dropped", 0),
    )
