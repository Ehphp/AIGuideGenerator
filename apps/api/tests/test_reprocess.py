"""Reprocess endpoint + reset_pipeline_state helper (no DB).

The endpoint integration is covered indirectly by the pipeline integration
tests; here we verify the unit-level invariants:

- `reset_pipeline_state` clears every JSON column and removes on-disk
  artifacts under `sessions/<id>/artifacts/` while preserving media.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.pipeline import common
from app.services import session_service


class _FakeDB:
    async def flush(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    from app.storage import local as storage_local

    monkeypatch.setattr(storage_local, "_default", None)
    return tmp_path


@pytest.mark.asyncio
async def test_reset_pipeline_state_wipes_db_columns_and_artifacts(tmp_storage):
    sid = uuid.uuid4()
    sess = SimpleNamespace(
        id=sid,
        pipeline_artifacts={"build_timeline": {"path": "x"}, "generate_guide": {}},
        pipeline_events=[{"stage": "ingest", "level": "info", "message": "ok"}],
        ai_usage={"approx_input_chars": 1234},
        guide_content={"title": "Stale guide"},
        guide_schema_version="1.0",
        guide_edited_at=None,
        progress_message="Guide ready",
        error="prior failure",
        media_key=f"sessions/{sid}/original.webm",
    )
    # Seed a couple of artifact files on disk.
    common.write_artifact(sid, "build_timeline", {"events": []})
    common.write_artifact(sid, "redaction_map.local", {"[EMAIL_1]": "a@x.it"})
    artifacts_dir = common.session_dir(sid) / "artifacts"
    # Also put a "media" file alongside that must NOT be touched.
    media_path = common.session_dir(sid) / "original.webm"
    media_path.write_bytes(b"fake-media")
    assert artifacts_dir.is_dir()
    assert (artifacts_dir / "build_timeline.json").is_file()

    await session_service.reset_pipeline_state(_FakeDB(), sess)

    # JSON columns wiped.
    assert sess.pipeline_artifacts == {}
    assert sess.pipeline_events == []
    assert sess.ai_usage == {}
    assert sess.guide_content is None
    assert sess.guide_schema_version is None
    assert sess.progress_message is None
    assert sess.error is None
    # Artifacts directory removed.
    assert not artifacts_dir.exists()
    # Media preserved.
    assert media_path.is_file()
    assert media_path.read_bytes() == b"fake-media"


@pytest.mark.asyncio
async def test_reset_pipeline_state_safe_when_nothing_to_clean(tmp_storage):
    sid = uuid.uuid4()
    sess = SimpleNamespace(
        id=sid,
        pipeline_artifacts={},
        pipeline_events=[],
        ai_usage={},
        guide_content=None,
        guide_schema_version=None,
        guide_edited_at=None,
        progress_message=None,
        error=None,
        media_key=None,
    )
    # Must not raise even though no artifacts dir exists.
    await session_service.reset_pipeline_state(_FakeDB(), sess)
