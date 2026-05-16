"""Phase D: ocr_frames_local stage + orchestrator OCR routing."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.local_models import OCRBBox, OCRBlock, OCRFrameResult, OCRResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(artifacts=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.pipeline_artifacts = artifacts or {}
    s.ai_usage = {}
    return s


def _make_db():
    db = AsyncMock(spec=AsyncSession)
    db.flush = AsyncMock()
    return db


def _ocr_response(frame_keys, text="hello world", with_blocks=True):
    blocks = (
        [OCRBlock(text="hello", confidence=0.9, bbox=OCRBBox(x=1, y=2, w=3, h=4))]
        if with_blocks else []
    )
    return OCRResponse(
        results=[
            OCRFrameResult(
                frame_key=k,
                engine="tesseract",
                model="tesseract",
                language="eng+ita",
                text=text,
                blocks=blocks,
            )
            for k in frame_keys
        ]
    )


def _patch_local_ai_client(monkeypatch, response):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.ocr = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "app.pipeline.stages.ocr_frames_local.LocalAIClient",
        lambda **kwargs: mock_client,
    )
    return mock_client


# ---------------------------------------------------------------------------
# Stage: artifact shape + idempotency + error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writes_analyze_frames_artifact(monkeypatch):
    from app.pipeline.stages import ocr_frames_local

    sid = uuid.uuid4()
    frames = [
        {"idx": 0, "t": 0.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
        {"idx": 1, "t": 1.5, "key": f"sessions/{sid}/frames/frame_0001.jpg"},
    ]
    session = _make_session(artifacts={"extract_frames": frames})
    db = _make_db()

    response = _ocr_response([f["key"] for f in frames], text="Click Save button")
    _patch_local_ai_client(monkeypatch, response)

    written = {}
    def fake_write(session_id, stage, payload):
        written[stage] = payload
        return f"sessions/{session_id}/artifacts/{stage}.json"

    recorded = []
    async def fake_record(db, session, *, stage, summary, message=None):
        recorded.append((stage, summary, message))

    monkeypatch.setattr("app.pipeline.common.write_artifact", fake_write)
    monkeypatch.setattr("app.pipeline.common.record_stage", fake_record)
    monkeypatch.setattr("app.pipeline.common.add_ai_call", AsyncMock())
    monkeypatch.setattr(
        "app.pipeline.common.artifact_storage_key",
        lambda sid, stage: f"sessions/{sid}/artifacts/{stage}.json",
    )

    await ocr_frames_local.run(db, session)

    # Artifact was written under the legacy key for transparent build_timeline.
    assert "analyze_frames" in written
    full = written["analyze_frames"]
    assert isinstance(full, list) and len(full) == 2
    assert full[0]["idx"] == 0
    assert full[0]["t"] == 0.0
    assert full[0]["ocr_text"] == "Click Save button"
    assert "UI text:" in full[0]["ui_summary"]
    assert full[0]["ocr"]["engine"] == "tesseract"
    assert full[0]["ocr"]["blocks"][0]["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}

    # Stage was recorded as "analyze_frames", with the public summary shape
    # (no `ocr` blob in the summary — only ocr_text + ui_summary).
    assert recorded[0][0] == "analyze_frames"
    summary = recorded[0][1]
    assert isinstance(summary, list) and len(summary) == 2
    assert summary[0].keys() >= {"idx", "t", "key", "ocr_text", "ui_summary"}
    assert "ocr" not in summary[0]


@pytest.mark.asyncio
async def test_skips_if_analyze_frames_already_done(monkeypatch):
    from app.pipeline.stages import ocr_frames_local

    session = _make_session(artifacts={"analyze_frames": [{"idx": 0}]})
    db = _make_db()
    mock_client = _patch_local_ai_client(monkeypatch, _ocr_response([]))

    await ocr_frames_local.run(db, session)
    mock_client.ocr.assert_not_called()


@pytest.mark.asyncio
async def test_raises_if_extract_frames_missing(monkeypatch):
    from app.pipeline.stages import ocr_frames_local
    db = _make_db()
    session = _make_session(artifacts={})
    with pytest.raises(RuntimeError, match="extract_frames"):
        await ocr_frames_local.run(db, session)


@pytest.mark.asyncio
async def test_wraps_local_ai_error(monkeypatch):
    from app.ai.local_client import LocalAITransportError
    from app.pipeline.stages import ocr_frames_local

    sid = uuid.uuid4()
    session = _make_session(artifacts={
        "extract_frames": [{"idx": 0, "t": 0.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"}]
    })
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.ocr = AsyncMock(side_effect=LocalAITransportError("boom"))
    monkeypatch.setattr(
        "app.pipeline.stages.ocr_frames_local.LocalAIClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(RuntimeError, match="local-ai ocr failed"):
        await ocr_frames_local.run(db, session)


# ---------------------------------------------------------------------------
# Privacy: only frame_keys sent — never image bytes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sends_frame_keys_not_bytes(monkeypatch):
    from app.pipeline.stages import ocr_frames_local

    sid = uuid.uuid4()
    keys = [
        f"sessions/{sid}/frames/frame_0000.jpg",
        f"sessions/{sid}/frames/frame_0001.jpg",
    ]
    frames = [{"idx": i, "t": float(i), "key": k} for i, k in enumerate(keys)]
    session = _make_session(artifacts={"extract_frames": frames})
    db = _make_db()

    captured = {}
    async def fake_ocr(**kwargs):
        captured.update(kwargs)
        return _ocr_response(keys)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.ocr = fake_ocr
    monkeypatch.setattr(
        "app.pipeline.stages.ocr_frames_local.LocalAIClient",
        lambda **kwargs: mock_client,
    )
    monkeypatch.setattr("app.pipeline.common.write_artifact", lambda *a, **kw: "x")
    monkeypatch.setattr("app.pipeline.common.record_stage", AsyncMock())
    monkeypatch.setattr("app.pipeline.common.add_ai_call", AsyncMock())
    monkeypatch.setattr(
        "app.pipeline.common.artifact_storage_key",
        lambda sid, stage: f"sessions/{sid}/artifacts/{stage}.json",
    )

    await ocr_frames_local.run(db, session)

    assert captured["frame_keys"] == keys
    # No bytes-shaped argument should be present.
    for forbidden in ("image_data", "frame_bytes", "files", "images"):
        assert forbidden not in captured


# ---------------------------------------------------------------------------
# Orchestrator routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_uses_legacy_analyze_frames_by_default(monkeypatch):
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.ocr_provider", "openai")

    legacy = []
    local_called = []

    async def fake_legacy(db, session, provider):
        legacy.append("legacy")

    async def fake_local(db, session):
        local_called.append("local")

    monkeypatch.setattr("app.pipeline.orchestrator.analyze_frames.run", fake_legacy)
    monkeypatch.setattr("app.pipeline.orchestrator.ocr_frames_local.run", fake_local)

    await orchestrator._run_analyze_frames(_make_db(), MagicMock(), provider=MagicMock())

    assert legacy == ["legacy"]
    assert local_called == []


@pytest.mark.asyncio
async def test_orchestrator_uses_local_ocr_when_ocr_provider_local(monkeypatch):
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.ocr_provider", "local")

    legacy = []
    local_called = []

    async def fake_legacy(db, session, provider):
        legacy.append("legacy")

    async def fake_local(db, session):
        local_called.append("local")

    monkeypatch.setattr("app.pipeline.orchestrator.analyze_frames.run", fake_legacy)
    monkeypatch.setattr("app.pipeline.orchestrator.ocr_frames_local.run", fake_local)

    await orchestrator._run_analyze_frames(_make_db(), MagicMock(), provider=MagicMock())

    assert legacy == []
    assert local_called == ["local"]


@pytest.mark.asyncio
async def test_orchestrator_does_not_call_vision_provider_when_local(monkeypatch):
    """When OCR_PROVIDER=local, GPT-4o Vision (provider.analyze_frame) is never invoked."""
    from app.pipeline import orchestrator

    monkeypatch.setattr("app.config.settings.ocr_provider", "local")

    async def fake_local(db, session):
        return None

    monkeypatch.setattr("app.pipeline.orchestrator.ocr_frames_local.run", fake_local)
    # Ensure the legacy stage cannot silently run.
    async def fake_legacy(db, session, provider):
        raise AssertionError("legacy analyze_frames must not be called when OCR_PROVIDER=local")
    monkeypatch.setattr("app.pipeline.orchestrator.analyze_frames.run", fake_legacy)

    explosive_provider = MagicMock()
    explosive_provider.analyze_frame = MagicMock(
        side_effect=AssertionError("GPT-4o Vision MUST NOT BE CALLED")
    )

    await orchestrator._run_analyze_frames(_make_db(), MagicMock(), provider=explosive_provider)

    explosive_provider.analyze_frame.assert_not_called()
