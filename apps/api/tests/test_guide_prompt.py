"""Tests asserting that guide_generation.md prompt is free of domain-specific
examples that could leak into unrelated guides, and that the internal-tool
filter is effective inside the sanitize_timeline stage.

These tests do NOT require Postgres or a running LLM.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.base import TextResult
from app.ai.fake_provider import FakeAIProvider
from app.config import settings
from app.pipeline import common
from app.pipeline.stages import generate_guide, sanitize_timeline


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_sanitize_pipeline.py pattern)
# ---------------------------------------------------------------------------


class _FakeDB:
    async def flush(self) -> None:
        pass


def _make_session(tmp_storage: Path) -> SimpleNamespace:
    sid = uuid.uuid4()
    return SimpleNamespace(
        id=sid,
        pipeline_artifacts={},
        ai_usage={},
        guide_content=None,
        guide_schema_version=None,
        guide_edited_at=None,
        media_duration_sec=None,
    )


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    from app.storage import local as storage_local
    monkeypatch.setattr(storage_local, "_default", None)
    return tmp_path


@pytest.fixture(autouse=True)
def _stub_session_service(monkeypatch):
    async def _update(db, sess, stage, summary):
        sess.pipeline_artifacts = {**(sess.pipeline_artifacts or {}), stage: summary}

    async def _append(db, sess, *, stage, level, message):
        return None

    from app.services import session_service
    monkeypatch.setattr(session_service, "update_pipeline_artifact", _update)
    monkeypatch.setattr(session_service, "append_pipeline_event", _append)


# ---------------------------------------------------------------------------
# Prompt content tests
# ---------------------------------------------------------------------------


class TestGuideGenerationPrompt:
    """guide_generation.md must not contain domain-specific example strings."""

    @pytest.fixture(scope="class")
    def prompt_text(self) -> str:
        p = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "pipeline"
            / "prompts"
            / "guide_generation.md"
        )
        return p.read_text(encoding="utf-8")

    BANNED_STRINGS = [
        "Valuemation",
        "Transfer Manager",
        "Export package",
        "Destination environment",
        "Package name",
        # Phrases that triggered the original cross-session contamination report.
        "workflow transfer",
        "transfer workflow",
        "transfer a workflow",
    ]

    @pytest.mark.parametrize("banned", BANNED_STRINGS)
    def test_banned_string_absent(self, prompt_text: str, banned: str):
        assert banned not in prompt_text, (
            f"guide_generation.md still contains banned domain-specific string: {banned!r}"
        )

    def test_hard_constraints_section_present(self, prompt_text: str):
        assert "Hard constraints" in prompt_text

    def test_timeline_marker_present(self, prompt_text: str):
        assert "TIMELINE:" in prompt_text

    def test_abstract_placeholder_examples_present(self, prompt_text: str):
        # At least one abstract placeholder should appear in the examples.
        assert "<Application>" in prompt_text or "<Menu Item>" in prompt_text


# ---------------------------------------------------------------------------
# sanitize_timeline integration: internal-tool prefix filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sanitize_drops_guide_generator_prefix(tmp_storage):
    """The sanitized timeline must not contain Guide Generator noise events
    that appear at the start of build_timeline."""
    sess = _make_session(tmp_storage)

    timeline = {
        "language": "en",
        "events": [
            {
                "kind": "transcript",
                "t": 0.0,
                "t_end": 1.0,
                "text": "Guide Generator ready Download DOCX Edit guide",
            },
            {
                "kind": "frame",
                "t": 0.5,
                "frame_key": "sessions/x/frames/frame_0001.jpg",
                "ocr_text": "Generate guide button",
                "ui_summary": "UI text: Generate guide button",
            },
            {
                "kind": "transcript",
                "t": 2.0,
                "t_end": 3.0,
                "text": "Open Docker Desktop Containers",
            },
        ],
    }
    common.write_artifact(sess.id, "build_timeline", timeline)

    await sanitize_timeline.run(_FakeDB(), sess)

    # build_timeline must be untouched.
    raw = common.read_artifact(sess.id, "build_timeline")
    assert len(raw["events"]) == 3, "build_timeline must preserve all raw events"

    sanitized = common.read_artifact(sess.id, "sanitize_timeline")
    assert sanitized is not None

    all_texts = " ".join(
        str(e.get("text", "") + e.get("ocr_text", "") + e.get("ui_summary", ""))
        for e in sanitized["events"]
    )
    assert "Guide Generator" not in all_texts
    assert "Download DOCX" not in all_texts
    assert "Generate guide" not in all_texts
    assert "Docker Desktop" in all_texts

    # DB summary carries the dropped count.
    summary = sess.pipeline_artifacts["sanitize_timeline"]
    assert summary["dropped_prefix_events"] == 2


@pytest.mark.asyncio
async def test_sanitize_keeps_noise_in_middle(tmp_storage):
    """Noise events that appear AFTER the first real event must be kept."""
    sess = _make_session(tmp_storage)

    timeline = {
        "language": "en",
        "events": [
            {
                "kind": "transcript",
                "t": 0.0,
                "t_end": 1.0,
                "text": "Open Docker Desktop",
            },
            {
                "kind": "transcript",
                "t": 1.0,
                "t_end": 2.0,
                "text": "Guide Generator ready",   # noise but NOT in prefix
            },
            {
                "kind": "transcript",
                "t": 2.0,
                "t_end": 3.0,
                "text": "Click Containers tab",
            },
        ],
    }
    common.write_artifact(sess.id, "build_timeline", timeline)

    await sanitize_timeline.run(_FakeDB(), sess)

    sanitized = common.read_artifact(sess.id, "sanitize_timeline")
    assert len(sanitized["events"]) == 3

    summary = sess.pipeline_artifacts["sanitize_timeline"]
    assert summary["dropped_prefix_events"] == 0


@pytest.mark.asyncio
async def test_sanitize_zero_dropped_when_no_noise(tmp_storage):
    sess = _make_session(tmp_storage)

    timeline = {
        "language": "en",
        "events": [
            {"kind": "transcript", "t": 0.0, "t_end": 1.0, "text": "Open terminal"},
            {"kind": "transcript", "t": 1.0, "t_end": 2.0, "text": "Run docker ps"},
        ],
    }
    common.write_artifact(sess.id, "build_timeline", timeline)

    await sanitize_timeline.run(_FakeDB(), sess)

    summary = sess.pipeline_artifacts["sanitize_timeline"]
    assert summary["dropped_prefix_events"] == 0
    sanitized = common.read_artifact(sess.id, "sanitize_timeline")
    assert len(sanitized["events"]) == 2


# ---------------------------------------------------------------------------
# Session isolation: prompt for session B must not contain session A tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_isolation_sanitized_artifact_does_not_leak_across_sessions(
    tmp_storage, monkeypatch
):
    """Two separate sessions must produce independent sanitized timeline artifacts.

    Session A contains 'Transfer Manager' (legacy example domain).
    Session B contains 'Docker Desktop Containers'.
    The sanitized artifact of B must not contain any token from A.
    """
    monkeypatch.setattr(settings, "sanitize_enabled", True)

    # --- Session A ---
    sess_a = _make_session(tmp_storage)
    timeline_a = {
        "language": "en",
        "events": [
            {
                "kind": "transcript",
                "t": 0.0,
                "t_end": 2.0,
                "text": "Open Transfer Manager and export the package",
            }
        ],
    }
    common.write_artifact(sess_a.id, "build_timeline", timeline_a)
    await sanitize_timeline.run(_FakeDB(), sess_a)

    # --- Session B ---
    sess_b = _make_session(tmp_storage)
    timeline_b = {
        "language": "en",
        "events": [
            {
                "kind": "transcript",
                "t": 0.0,
                "t_end": 2.0,
                "text": "Open Docker Desktop Containers",
            }
        ],
    }
    common.write_artifact(sess_b.id, "build_timeline", timeline_b)
    await sanitize_timeline.run(_FakeDB(), sess_b)

    sanitized_b = common.read_artifact(sess_b.id, "sanitize_timeline")
    assert sanitized_b is not None

    b_text = json.dumps(sanitized_b)
    assert "Transfer Manager" not in b_text
    assert "export the package" not in b_text
    assert "Docker Desktop" in b_text


@pytest.mark.asyncio
async def test_session_isolation_llm_prompt_does_not_leak_across_sessions(
    tmp_storage, monkeypatch
):
    """The LLM prompt built by generate_guide for session B must not contain
    any text that was written only into session A's sanitized timeline.

    This verifies the actual prompt string, not just the artifact on disk.
    """
    monkeypatch.setattr(settings, "sanitize_enabled", True)

    # --- Session A: sanitize then generate (so its artifact exists on disk) ---
    sess_a = _make_session(tmp_storage)
    common.write_artifact(
        sess_a.id,
        "build_timeline",
        {
            "language": "en",
            "events": [
                {
                    "kind": "transcript",
                    "t": 0.0,
                    "t_end": 2.0,
                    "text": "Open Transfer Manager and export the package",
                }
            ],
        },
    )
    await sanitize_timeline.run(_FakeDB(), sess_a)

    # --- Session B: build its own sanitized timeline ---
    sess_b = _make_session(tmp_storage)
    common.write_artifact(
        sess_b.id,
        "build_timeline",
        {
            "language": "en",
            "events": [
                {
                    "kind": "transcript",
                    "t": 0.0,
                    "t_end": 2.0,
                    "text": "Open Docker Desktop Containers",
                }
            ],
        },
    )
    await sanitize_timeline.run(_FakeDB(), sess_b)

    # Intercept the prompt actually sent to the LLM by generate_guide.
    captured: dict = {}

    class _SpyProvider(FakeAIProvider):
        async def generate_json(self, *, prompt: str) -> TextResult:
            captured["prompt"] = prompt
            return await super().generate_json(prompt=prompt)

    await generate_guide.run(_FakeDB(), sess_b, _SpyProvider())

    assert "prompt" in captured, "generate_guide did not call the provider"
    prompt = captured["prompt"]

    # Session B's prompt must contain its own content.
    assert "Docker Desktop" in prompt

    # Session B's prompt must NOT contain anything exclusive to session A.
    assert "Transfer Manager" not in prompt
    assert "export the package" not in prompt
