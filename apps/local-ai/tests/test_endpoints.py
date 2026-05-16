"""Phase B: /health, /transcribe, /ocr stubs."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import storage_resolver
from app.config import settings
from app.main import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Point the resolver at an isolated tmp root for the whole test.
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    return TestClient(app)


@pytest.fixture()
def session_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def audio_key(tmp_path: Path, session_id: str) -> str:
    p = tmp_path / "sessions" / session_id / "audio.wav"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"RIFF")
    return f"sessions/{session_id}/audio.wav"


@pytest.fixture()
def frame_keys(tmp_path: Path, session_id: str) -> list[str]:
    base = tmp_path / "sessions" / session_id / "frames"
    base.mkdir(parents=True)
    keys = []
    for i in (1, 2):
        p = base / f"frame_{i:04d}.jpg"
        p.write_bytes(b"\xff\xd8\xff")
        keys.append(f"sessions/{session_id}/frames/frame_{i:04d}.jpg")
    return keys


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# /transcribe stub
# ---------------------------------------------------------------------------


def test_transcribe_stub_validates_and_returns_empty(client, audio_key):
    r = client.post("/transcribe", json={"audio_key": audio_key, "language": "it"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == ""
    assert body["segments"] == []
    assert body["language"] == "it"
    assert body["engine"] == "stub"
    assert body["model"] == "stub"


def test_transcribe_rejects_missing_audio_key(client, session_id):
    r = client.post(
        "/transcribe",
        json={"audio_key": f"sessions/{session_id}/audio.wav", "language": "it"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["category"] == "not_found"


def test_transcribe_rejects_traversal(client):
    r = client.post(
        "/transcribe",
        json={"audio_key": "../etc/passwd", "language": "it"},
    )
    assert r.status_code == 400
    assert r.json()["category"] == "invalid_key"


def test_transcribe_rejects_absolute_path(client):
    r = client.post(
        "/transcribe",
        json={"audio_key": "/data/storage/sessions/x/audio.wav"},
    )
    assert r.status_code == 400
    assert r.json()["category"] == "invalid_key"


def test_transcribe_rejects_non_session_prefix(client):
    r = client.post(
        "/transcribe",
        json={"audio_key": "models/whisper.bin"},
    )
    assert r.status_code == 400
    assert r.json()["category"] == "invalid_key"


def test_transcribe_rejects_empty_audio_key(client):
    r = client.post("/transcribe", json={"audio_key": ""})
    # Pydantic min_length validation triggers FastAPI 422.
    assert r.status_code == 422


def test_transcribe_response_does_not_leak_storage_root(client, audio_key):
    r = client.post("/transcribe", json={"audio_key": audio_key})
    assert r.status_code == 200
    assert "/data/storage" not in r.text


# ---------------------------------------------------------------------------
# /ocr stub
# ---------------------------------------------------------------------------


def test_ocr_stub_validates_and_returns_one_per_key(client, frame_keys):
    r = client.post("/ocr", json={"frame_keys": frame_keys, "language": "it"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == len(frame_keys)
    for key, result in zip(frame_keys, body["results"], strict=True):
        assert result["frame_key"] == key
        assert result["text"] == ""
        assert result["blocks"] == []
        assert result["engine"] == "stub"
        assert result["model"] == "stub"
        assert result["language"] == "it"


def test_ocr_rejects_when_any_key_invalid(client, frame_keys):
    bad = [frame_keys[0], "../etc/passwd"]
    r = client.post("/ocr", json={"frame_keys": bad})
    assert r.status_code == 400
    assert r.json()["category"] == "invalid_key"


def test_ocr_rejects_when_any_key_missing(client, frame_keys, session_id):
    missing = [frame_keys[0], f"sessions/{session_id}/frames/frame_9999.jpg"]
    r = client.post("/ocr", json={"frame_keys": missing})
    assert r.status_code == 404
    assert r.json()["category"] == "not_found"


def test_ocr_rejects_empty_frame_keys(client):
    r = client.post("/ocr", json={"frame_keys": []})
    assert r.status_code == 422


def test_ocr_response_does_not_leak_storage_root(client, frame_keys):
    r = client.post("/ocr", json={"frame_keys": frame_keys})
    assert r.status_code == 200
    assert "/data/storage" not in r.text


# ---------------------------------------------------------------------------
# Phase D: /ocr with real engine dispatch (mocked)
# ---------------------------------------------------------------------------


def test_ocr_default_engine_is_stub():
    """Confirm the default settings.ocr_engine is 'stub' so tests stay fast."""
    assert settings.ocr_engine == "stub"


def test_ocr_dispatches_to_engine_when_not_stub(client, frame_keys, monkeypatch):
    """When OCR_ENGINE != 'stub', the endpoint must call ocr_engine.ocr_frames."""
    from app import ocr_engine

    monkeypatch.setattr(settings, "ocr_engine", "tesseract")

    captured = {}
    def fake_ocr_frames(frame_paths, frame_keys, language):
        captured["paths"] = list(frame_paths)
        captured["keys"] = list(frame_keys)
        captured["language"] = language
        return [
            {
                "frame_key": k,
                "engine": "tesseract",
                "model": "tesseract",
                "language": language,
                "text": "Sample UI",
                "blocks": [
                    {"text": "Sample", "confidence": 0.91,
                     "bbox": {"x": 10, "y": 20, "w": 40, "h": 12}},
                ],
            }
            for k in frame_keys
        ]
    monkeypatch.setattr(ocr_engine, "ocr_frames", fake_ocr_frames)

    r = client.post("/ocr", json={"frame_keys": frame_keys, "language": "ita"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == len(frame_keys)
    for res in body["results"]:
        assert res["engine"] == "tesseract"
        assert res["text"] == "Sample UI"
        assert res["blocks"][0]["bbox"] == {"x": 10, "y": 20, "w": 40, "h": 12}
    # Endpoint passed the resolved Paths through to the engine, never the keys-as-paths.
    assert all(isinstance(p, Path) for p in captured["paths"])
    assert captured["keys"] == frame_keys
    assert captured["language"] == "ita"


def test_ocr_rejects_request_above_max_frames_per_request(client, frame_keys, monkeypatch):
    monkeypatch.setattr(settings, "ocr_max_frames_per_request", 1)
    r = client.post("/ocr", json={"frame_keys": frame_keys})
    assert r.status_code == 400
    assert r.json()["category"] == "invalid_key"


def test_ocr_endpoint_does_not_log_text(client, frame_keys, monkeypatch, caplog):
    """The endpoint must not log OCR text content."""
    from app import ocr_engine

    monkeypatch.setattr(settings, "ocr_engine", "tesseract")
    secret = "TOP-SECRET-OCR-1234"
    monkeypatch.setattr(
        ocr_engine, "ocr_frames",
        lambda frame_paths, frame_keys, language: [
            {"frame_key": k, "engine": "tesseract", "model": "tesseract",
             "language": language, "text": secret, "blocks": []}
            for k in frame_keys
        ],
    )
    with caplog.at_level("DEBUG"):
        r = client.post("/ocr", json={"frame_keys": frame_keys})
    assert r.status_code == 200
    assert secret not in caplog.text


# ---------------------------------------------------------------------------
# Sanity: resolver constants visible to the endpoint layer
# ---------------------------------------------------------------------------


def test_resolver_module_exports_expected_errors():
    # Guards against accidental rename that would silently broaden the API.
    assert hasattr(storage_resolver, "StorageKeyError")
    assert hasattr(storage_resolver, "StorageNotFoundError")
    assert hasattr(storage_resolver, "resolve_storage_key")
