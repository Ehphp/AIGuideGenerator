"""Phase C: transcribe_local stage + orchestrator routing."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.local_models import TranscribeResponse, TranscribeSegment


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_session(artifacts: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.pipeline_artifacts = artifacts or {}
    s.ai_usage = {}
    return s


def _make_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.flush = AsyncMock()
    return db


def _stub_transcribe_response(text="Hello world", language="it") -> TranscribeResponse:
    return TranscribeResponse(
        text=text,
        language=language,
        segments=[TranscribeSegment(start=0.0, end=2.5, text=text)],
        engine="stub",
        model="stub",
    )


# ---------------------------------------------------------------------------
# transcribe_local stage: artifact shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_local_writes_transcribe_artifact(tmp_path, monkeypatch):
    """transcribe_local must write artifact under key 'transcribe'."""
    from app.pipeline.stages import transcribe_local

    session = _make_session(
        artifacts={"extract_audio": {"audio_key": f"sessions/{uuid.uuid4()}/audio.wav"}}
    )
    db = _make_db()

    written: dict = {}

    def _fake_write(session_id, stage, payload):
        written[stage] = payload
        return f"sessions/{session_id}/artifacts/{stage}.json"

    recorded: list = []

    async def _fake_record(db, session, *, stage, summary, message=None):
        recorded.append((stage, summary))

    async def _fake_add_ai_call(db, session, *, stage, model, **kwargs):
        pass

    response = _stub_transcribe_response()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.transcribe = AsyncMock(return_value=response)

    monkeypatch.setattr("app.pipeline.stages.transcribe_local.LocalAIClient",
                        lambda **kwargs: mock_client)
    monkeypatch.setattr("app.pipeline.common.write_artifact", _fake_write)
    monkeypatch.setattr("app.pipeline.common.record_stage", _fake_record)
    monkeypatch.setattr("app.pipeline.common.add_ai_call", _fake_add_ai_call)
    monkeypatch.setattr("app.pipeline.common.artifact_storage_key",
                        lambda sid, stage: f"sessions/{sid}/artifacts/{stage}.json")

    await transcribe_local.run(db, session)

    # Artifact written as "transcribe" so downstream stages are unaffected.
    assert "transcribe" in written
    art = written["transcribe"]
    assert art["text"] == "Hello world"
    assert art["language"] == "it"
    assert len(art["segments"]) == 1
    assert art["engine"] == "stub"
    assert art["model"] == "stub"

    # Summary recorded as stage="transcribe".
    assert recorded[0][0] == "transcribe"
    summary = recorded[0][1]
    assert summary["segment_count"] == 1
    assert summary["language"] == "it"
    assert "path" in summary


@pytest.mark.asyncio
async def test_transcribe_local_skips_if_already_done(monkeypatch):
    from app.pipeline.stages import transcribe_local

    session = _make_session(artifacts={"transcribe": {"path": "x", "segment_count": 3}})
    db = _make_db()

    called = []

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.transcribe = AsyncMock(side_effect=lambda **kw: called.append(1))

    monkeypatch.setattr("app.pipeline.stages.transcribe_local.LocalAIClient",
                        lambda **kwargs: mock_client)

    await transcribe_local.run(db, session)
    assert called == []  # no client call — already done


@pytest.mark.asyncio
async def test_transcribe_local_raises_if_no_extract_audio():
    from app.pipeline.stages import transcribe_local

    session = _make_session(artifacts={})
    db = _make_db()

    with pytest.raises(RuntimeError, match="extract_audio"):
        await transcribe_local.run(db, session)


@pytest.mark.asyncio
async def test_transcribe_local_wraps_local_ai_error(monkeypatch):
    from app.ai.local_client import LocalAITransportError
    from app.pipeline.stages import transcribe_local

    session = _make_session(
        artifacts={"extract_audio": {"audio_key": f"sessions/{uuid.uuid4()}/audio.wav"}}
    )
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.transcribe = AsyncMock(
        side_effect=LocalAITransportError("connection refused")
    )
    monkeypatch.setattr("app.pipeline.stages.transcribe_local.LocalAIClient",
                        lambda **kwargs: mock_client)

    with pytest.raises(RuntimeError, match="local-ai transcribe failed"):
        await transcribe_local.run(db, session)


# ---------------------------------------------------------------------------
# Safety: only the storage KEY is sent — never raw audio bytes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_local_sends_key_not_bytes(monkeypatch):
    """LocalAIClient.transcribe must be called with audio_key, not file bytes."""
    from app.pipeline.stages import transcribe_local

    sid = uuid.uuid4()
    expected_key = f"sessions/{sid}/audio.wav"
    session = _make_session(artifacts={"extract_audio": {"audio_key": expected_key}})
    db = _make_db()

    calls: list[dict] = []
    response = _stub_transcribe_response()

    async def _fake_transcribe(**kwargs):
        calls.append(kwargs)
        return response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.transcribe = _fake_transcribe

    monkeypatch.setattr("app.pipeline.stages.transcribe_local.LocalAIClient",
                        lambda **kwargs: mock_client)
    monkeypatch.setattr("app.pipeline.common.write_artifact", lambda *a, **kw: "x")
    monkeypatch.setattr("app.pipeline.common.record_stage", AsyncMock())
    monkeypatch.setattr("app.pipeline.common.add_ai_call", AsyncMock())
    monkeypatch.setattr("app.pipeline.common.artifact_storage_key",
                        lambda sid, stage: f"sessions/{sid}/artifacts/{stage}.json")

    await transcribe_local.run(db, session)

    assert len(calls) == 1
    call = calls[0]
    # Key sent, not bytes.
    assert call["audio_key"] == expected_key
    assert "audio_key" in call
    # Confirm no raw bytes argument exists.
    assert "audio_data" not in call
    assert "audio_bytes" not in call
    assert "file" not in call


# ---------------------------------------------------------------------------
# Orchestrator routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_uses_legacy_transcribe_by_default(monkeypatch):
    """Default stt_provider='openai' → legacy transcribe stage called."""
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.stt_provider", "openai")

    legacy_called = []
    local_called = []

    async def _fake_legacy(db, session, provider):
        legacy_called.append(1)

    async def _fake_local(db, session):
        local_called.append(1)

    monkeypatch.setattr("app.pipeline.orchestrator.transcribe.run", _fake_legacy)
    monkeypatch.setattr("app.pipeline.orchestrator.transcribe_local.run", _fake_local)

    session = MagicMock()
    session.pipeline_artifacts = {"transcribe": {"path": "x"}}
    db = _make_db()

    await orchestrator._run_transcribe(db, session, provider=MagicMock())

    # With transcribe already in artifacts, the inner stage_done short-circuits.
    # Confirm the correct *branch* was taken regardless.
    assert local_called == []
    assert legacy_called == [1]


@pytest.mark.asyncio
async def test_orchestrator_uses_local_transcribe_when_stt_provider_local(monkeypatch):
    """stt_provider='local' → transcribe_local stage called; legacy skipped."""
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.stt_provider", "local")

    legacy_called = []
    local_called = []

    async def _fake_legacy(db, session, provider):
        legacy_called.append(1)

    async def _fake_local(db, session):
        local_called.append(1)

    monkeypatch.setattr("app.pipeline.orchestrator.transcribe.run", _fake_legacy)
    monkeypatch.setattr("app.pipeline.orchestrator.transcribe_local.run", _fake_local)

    session = MagicMock()
    db = _make_db()

    await orchestrator._run_transcribe(db, session, provider=MagicMock())

    assert local_called == [1]
    assert legacy_called == []


@pytest.mark.asyncio
async def test_orchestrator_fake_provider_uses_legacy_path(monkeypatch):
    """stt_provider='fake' is not 'local' → legacy path."""
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.stt_provider", "fake")

    legacy_called = []

    async def _fake_legacy(db, session, provider):
        legacy_called.append(1)

    monkeypatch.setattr("app.pipeline.orchestrator.transcribe.run", _fake_legacy)
    monkeypatch.setattr("app.pipeline.orchestrator.transcribe_local.run", AsyncMock())

    session = MagicMock()
    db = _make_db()
    await orchestrator._run_transcribe(db, session, provider=MagicMock())

    assert legacy_called == [1]
