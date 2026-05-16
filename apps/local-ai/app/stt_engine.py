"""STT engine abstraction for the local-ai service.

Phase C: faster-whisper integration.

Design:
- The model is loaded lazily on first use and cached in-process.
- A threading.Lock protects the singleton so concurrent requests share one
  model instance rather than racing to load several.
- `faster-whisper` is an optional dependency (see pyproject.toml `[stt]`
  extra). If it is not installed and someone tries to use the engine, a
  clear `ImportError` is raised rather than a cryptic AttributeError.
- `transcribe()` accepts a filesystem `Path` (already resolved and validated
  by `storage_resolver`). It never logs the path value.
- Segments are consumed eagerly from the generator before returning, so the
  caller can safely use the result after the function returns.

Stub mode:
- If `settings.stt_engine != "faster_whisper"` this module is never called;
  `main.py` returns the stub response directly. The lazy load therefore only
  runs in faster_whisper mode.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None  # type: ignore[var-annotated]  # WhisperModel | None


def _get_model():  # noqa: ANN201
    """Return the cached WhisperModel, loading it on first call."""
    global _model  # noqa: PLW0603
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is not installed; install the [stt] extra or "
                "set STT_ENGINE=stub"
            ) from exc

        log.info(
            "loading faster-whisper model (model=%s device=%s compute_type=%s)",
            settings.whisper_model,
            settings.whisper_device,
            settings.whisper_compute_type,
        )
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        log.info("faster-whisper model loaded")
    return _model


def transcribe(audio_path: Path) -> dict:
    """Transcribe *audio_path* using faster-whisper.

    Returns a dict matching the TranscribeResponse schema.
    Raises ImportError if faster-whisper is not installed.
    Raises RuntimeError on engine-level failures.
    """
    model = _get_model()
    language = settings.whisper_language.strip() or None

    # Consume the segment generator immediately; the generator holds an
    # internal reference to the audio and must not be abandoned.
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
    )

    seg_list: list[dict] = []
    text_parts: list[str] = []
    for seg in segments_gen:
        seg_list.append(
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
            }
        )
        text_parts.append(seg.text)  # preserve original spacing for concatenation

    # faster-whisper segments include their own leading/trailing spaces, so
    # concatenating without a separator gives correct inter-word spacing.
    full_text = "".join(text_parts).strip()

    return {
        "text": full_text,
        "language": info.language,
        "segments": seg_list,
        "engine": "faster_whisper",
        "model": settings.whisper_model,
    }


def reset_model_cache() -> None:
    """Evict the cached model. Used in tests only."""
    global _model  # noqa: PLW0603
    with _lock:
        _model = None
