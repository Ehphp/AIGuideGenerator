"""Phase E: integration tests for sanitize_timeline + rehydrate_guide stages
and the generate_guide / validate_guide sanitized boundary.

These do NOT require Postgres — they exercise the file-based artifact API
and the public stage entrypoints with a stub session and a fake provider.
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
from app.pipeline import common, safety
from app.pipeline.stages import (
    generate_guide,
    rehydrate_guide,
    sanitize_timeline,
    validate_guide,
)


# --------------------------------------------------------------------------
# Helpers — bypass DB by using an in-memory stand-in for `Session`.
# --------------------------------------------------------------------------


class _FakeDB:
    async def flush(self) -> None:  # pragma: no cover - trivial
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
        media_duration_sec=1.0,
    )


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """Point the local storage backend at a temp dir for the test."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    # Reset the cached storage singleton so the new path takes effect.
    from app.storage import local as storage_local

    monkeypatch.setattr(storage_local, "_default", None)
    return tmp_path


# Patch the two helpers from session_service that record_stage calls — we
# don't need real DB writes here, just artifact files + the in-memory
# pipeline_artifacts dict.
@pytest.fixture(autouse=True)
def _stub_session_service(monkeypatch):
    async def _update(db, sess, stage, summary):
        sess.pipeline_artifacts = {**(sess.pipeline_artifacts or {}), stage: summary}

    async def _append(db, sess, *, stage, level, message):
        return None

    from app.services import session_service

    monkeypatch.setattr(session_service, "update_pipeline_artifact", _update)
    monkeypatch.setattr(session_service, "append_pipeline_event", _append)


# --------------------------------------------------------------------------
# sanitize_timeline stage
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sanitize_timeline_writes_sanitized_artifact_and_local_map(tmp_storage):
    sess = _make_session(tmp_storage)
    timeline = {
        "language": "it",
        "events": [
            {"kind": "transcript", "t": 0.0, "t_end": 1.0, "text": "mail a@x.it"},
            {
                "kind": "frame",
                "t": 1.5,
                "frame_key": "frames/000.jpg",
                "ocr_text": "IP 10.0.0.1",
                "ui_summary": "Login",
            },
        ],
    }
    common.write_artifact(sess.id, "build_timeline", timeline)

    await sanitize_timeline.run(_FakeDB(), sess)

    sanitized = common.read_artifact(sess.id, "sanitize_timeline")
    assert sanitized is not None
    assert sanitized["events"][0]["text"] == "mail [EMAIL_1]"
    assert sanitized["events"][1]["ocr_text"] == "IP [IPV4_1]"

    # Redaction map written to a sibling artifact file.
    map_path = common.artifact_path(sess.id, "redaction_map.local")
    assert map_path.is_file()
    rmap = json.loads(map_path.read_text())
    assert rmap["[EMAIL_1]"] == "a@x.it"
    assert rmap["[IPV4_1]"] == "10.0.0.1"

    # DB summary stores counts only — no values, no map content.
    summary = sess.pipeline_artifacts["sanitize_timeline"]
    assert summary["placeholder_count"] == 2
    assert summary["categories"] == {"EMAIL": 1, "IPV4": 1}
    assert summary["redaction_map_present"] is True
    assert "a@x.it" not in json.dumps(summary)


@pytest.mark.asyncio
async def test_sanitized_artifact_passes_safety_smoke(tmp_storage):
    sess = _make_session(tmp_storage)
    common.write_artifact(
        sess.id,
        "build_timeline",
        {
            "language": "en",
            "events": [
                {"kind": "transcript", "t": 0.0, "t_end": 1.0, "text": "ping a@x.it on 10.0.0.1"}
            ],
        },
    )
    await sanitize_timeline.run(_FakeDB(), sess)

    sanitized = common.read_artifact(sess.id, "sanitize_timeline")
    # Must not trip the leak-tripwire detectors.
    safety.assert_not_raw_artifact(sanitized, context="test")


# --------------------------------------------------------------------------
# generate_guide boundary
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_guide_reads_sanitized_when_flag_on(tmp_storage, monkeypatch):
    sess = _make_session(tmp_storage)
    monkeypatch.setattr(settings, "sanitize_enabled", True)

    # Only write the sanitized artifact — generate_guide MUST NOT fall back
    # to build_timeline when the flag is on.
    common.write_artifact(
        sess.id,
        "sanitize_timeline",
        {"language": "en", "events": [{"kind": "transcript", "t": 0.0, "text": "click [EMAIL_1]"}]},
    )

    captured = {}

    class _SpyProvider(FakeAIProvider):
        async def generate_json(self, *, prompt: str) -> TextResult:  # type: ignore[override]
            captured["prompt"] = prompt
            return await super().generate_json(prompt=prompt)

    await generate_guide.run(_FakeDB(), sess, _SpyProvider())

    # The prompt must contain the placeholder, not any raw value, and must
    # not trip the leak detectors.
    assert "[EMAIL_1]" in captured["prompt"]
    safety.assert_not_raw_artifact(captured["prompt"], context="test")


@pytest.mark.asyncio
async def test_generate_guide_refuses_to_run_without_sanitized_artifact(
    tmp_storage, monkeypatch
):
    sess = _make_session(tmp_storage)
    monkeypatch.setattr(settings, "sanitize_enabled", True)
    # Only the raw build_timeline exists.
    common.write_artifact(
        sess.id,
        "build_timeline",
        {"language": "en", "events": [{"kind": "transcript", "t": 0.0, "text": "x"}]},
    )

    with pytest.raises(RuntimeError):
        await generate_guide.run(_FakeDB(), sess, FakeAIProvider())


@pytest.mark.asyncio
async def test_generate_guide_legacy_path_unchanged_when_flag_off(
    tmp_storage, monkeypatch
):
    sess = _make_session(tmp_storage)
    monkeypatch.setattr(settings, "sanitize_enabled", False)
    common.write_artifact(
        sess.id,
        "build_timeline",
        {"language": "en", "events": [{"kind": "transcript", "t": 0.0, "text": "click x"}]},
    )

    await generate_guide.run(_FakeDB(), sess, FakeAIProvider())
    art = common.read_artifact(sess.id, "generate_guide")
    assert art is not None and "raw_text" in art


# --------------------------------------------------------------------------
# rehydrate_guide + validate_guide
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rehydrate_guide_resolves_placeholders(tmp_storage):
    sess = _make_session(tmp_storage)
    # Seed the redaction map.
    map_path = common.artifact_path(sess.id, "redaction_map.local")
    map_path.write_text(json.dumps({"[EMAIL_1]": "a@x.it"}))
    # Seed the placeholder guide text (as if generate_guide produced it).
    common.write_artifact(
        sess.id,
        "generate_guide",
        {"prompt_chars": 10, "raw_text": '{"hi":"send to [EMAIL_1]"}', "raw": {}},
    )

    await rehydrate_guide.run(_FakeDB(), sess)

    art = common.read_artifact(sess.id, "rehydrate_guide")
    assert art["raw_text"] == '{"hi":"send to a@x.it"}'
    assert art["placeholders_resolved"] == 1
    assert art["placeholders_unresolved"] == 0


@pytest.mark.asyncio
async def test_validate_guide_uses_rehydrated_when_flag_on(tmp_storage, monkeypatch):
    sess = _make_session(tmp_storage)
    monkeypatch.setattr(settings, "sanitize_enabled", True)

    # Build a minimal valid Guide document (matches Guide schema v1.0).
    valid_guide = {
        "schema_version": "1.0",
        "title": "Reset password for a@x.it",
        "summary": "Help reset the account.",
        "estimated_duration_minutes": 1.0,
        "prerequisites": [],
        "tools_or_systems": [],
        "steps": [
            {
                "id": "step-1",
                "order": 1,
                "title": "Open portal",
                "description": "Open the portal.",
                "actions": [{"verb": "open", "target": "portal"}],
                "evidence": {"frame_keys": [], "transcript_excerpt": "", "timestamp_sec": 0.0},
            }
        ],
        "metadata": {
            "generated_at": "",
            "source_session_id": "",
            "source_duration_sec": None,
        },
    }
    rehydrated_text = json.dumps(valid_guide)
    placeholder_text = rehydrated_text.replace("a@x.it", "[EMAIL_1]")

    common.write_artifact(
        sess.id,
        "rehydrate_guide",
        {
            "placeholder_text": placeholder_text,
            "raw_text": rehydrated_text,
            "placeholders_resolved": 1,
            "placeholders_unresolved": 0,
        },
    )

    await validate_guide.run(_FakeDB(), sess, FakeAIProvider())

    assert sess.guide_content is not None
    # Final guide contains the rehydrated value.
    assert "a@x.it" in sess.guide_content["title"]
