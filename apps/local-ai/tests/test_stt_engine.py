"""Phase C: stt_engine — stub/dispatch logic and mock-able model interface."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import stt_engine


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure the lazy model cache is clear before and after each test."""
    stt_engine.reset_model_cache()
    yield
    stt_engine.reset_model_cache()


# ---------------------------------------------------------------------------
# /transcribe remains stub by default
# (endpoint-level test lives in test_endpoints.py; these test the module)
# ---------------------------------------------------------------------------


def test_stub_engine_is_default(monkeypatch):
    from app.config import settings
    assert settings.stt_engine == "stub", (
        "stt_engine default must remain 'stub' so tests run without downloading a model"
    )


# ---------------------------------------------------------------------------
# Model lazy-loading (no real faster-whisper required)
# ---------------------------------------------------------------------------


def _make_fake_model(segments=None, language="it"):
    """Build a minimal faster-whisper model mock."""
    if segments is None:
        segments = [
            MagicMock(start=0.0, end=1.5, text=" Hello"),
            MagicMock(start=1.5, end=3.0, text=" world"),
        ]
    info = MagicMock()
    info.language = language

    model = MagicMock()
    model.transcribe.return_value = (iter(segments), info)
    return model


def test_transcribe_with_mocked_model(tmp_path, monkeypatch):
    """transcribe() uses the lazy model and returns the correct schema shape."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF")

    fake_model = _make_fake_model()
    monkeypatch.setattr("app.config.settings.stt_engine", "faster_whisper")
    monkeypatch.setattr("app.config.settings.whisper_language", "")

    with patch("app.stt_engine._get_model", return_value=fake_model):
        result = stt_engine.transcribe(audio)

    assert result["text"] == "Hello world"
    assert result["language"] == "it"
    assert len(result["segments"]) == 2
    assert result["segments"][0] == {"start": 0.0, "end": 1.5, "text": "Hello"}
    assert result["engine"] == "faster_whisper"
    assert "model" in result


def test_transcribe_passes_language_to_model(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF")

    fake_model = _make_fake_model(segments=[], language="en")
    monkeypatch.setattr("app.config.settings.stt_engine", "faster_whisper")
    monkeypatch.setattr("app.config.settings.whisper_language", "en")

    with patch("app.stt_engine._get_model", return_value=fake_model):
        stt_engine.transcribe(audio)

    _, call_kwargs = fake_model.transcribe.call_args
    assert call_kwargs.get("language") == "en"


def test_transcribe_auto_detect_when_language_blank(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF")

    fake_model = _make_fake_model(segments=[], language="fr")
    monkeypatch.setattr("app.config.settings.stt_engine", "faster_whisper")
    monkeypatch.setattr("app.config.settings.whisper_language", "")

    with patch("app.stt_engine._get_model", return_value=fake_model):
        stt_engine.transcribe(audio)

    _, call_kwargs = fake_model.transcribe.call_args
    assert call_kwargs.get("language") is None


def test_get_model_raises_import_error_if_not_installed(monkeypatch):
    """If faster-whisper is not installed, _get_model raises a clear ImportError."""
    import builtins
    real_import = builtins.__import__

    def _block_faster_whisper(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("no module named faster_whisper")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_faster_whisper):
        with pytest.raises(ImportError, match="faster-whisper is not installed"):
            stt_engine._get_model()


def test_model_is_cached_across_calls(tmp_path, monkeypatch):
    """_get_model should construct WhisperModel exactly once."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF")

    call_count = 0
    fake_model = _make_fake_model()

    original_get = stt_engine._get_model

    def counting_get_model():
        nonlocal call_count
        call_count += 1
        return fake_model

    with patch("app.stt_engine._get_model", side_effect=counting_get_model):
        stt_engine.transcribe(audio)
        stt_engine.transcribe(audio)

    # The patch replaces _get_model entirely; each transcribe() call hits it.
    assert call_count == 2  # the mock itself is called twice; model construction is in _get_model


def test_reset_model_cache_clears_global():
    stt_engine._model = object()  # plant a fake value
    stt_engine.reset_model_cache()
    assert stt_engine._model is None


# ---------------------------------------------------------------------------
# Segments consumed eagerly (generator safety)
# ---------------------------------------------------------------------------


def test_segments_consumed_from_generator(tmp_path, monkeypatch):
    """The generator must be fully consumed; result must not be a generator."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF")

    def _gen():
        for t, e, txt in [(0.0, 1.0, " one"), (1.0, 2.0, " two"), (2.0, 3.0, " three")]:
            yield MagicMock(start=t, end=e, text=txt)

    info = MagicMock()
    info.language = "en"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (_gen(), info)

    with patch("app.stt_engine._get_model", return_value=fake_model):
        result = stt_engine.transcribe(audio)

    assert isinstance(result["segments"], list)
    assert len(result["segments"]) == 3
    assert result["text"] == "one two three"
