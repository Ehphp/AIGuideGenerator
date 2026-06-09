"""Stage: extract_audio. ffmpeg -> 16kHz mono wav."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage

log = logging.getLogger(__name__)

# OpenAI Whisper API file-size limit is 25 MB.  Stay 2 MB under to leave a
# margin for HTTP overhead.  A 16 kHz mono WAV exceeds this at ~12.3 minutes.
_OPENAI_SAFE_BYTES = 23 * 1024 * 1024


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "extract_audio"):
        return
    if not session.media_key:
        raise RuntimeError("session has no media_key")

    storage = get_storage()
    src = storage.local_path(session.media_key)
    audio_key = f"sessions/{session.id}/audio.wav"
    dst = storage.local_path(audio_key)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Timeout: at least 5 min, or 2.5× the recorded duration.
    # media_duration_sec is populated by the ingest stage.
    _duration = session.media_duration_sec or 1200.0
    _ffmpeg_timeout = max(300.0, _duration * 2.5)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", str(settings.audio_sample_rate),
        "-f", "wav",
        str(dst),
    ]
    await common.run_ffmpeg(
        cmd,
        timeout_sec=_ffmpeg_timeout,
        cleanup_paths=[dst],
        error_prefix="ffmpeg extract_audio",
    )

    wav_size = dst.stat().st_size if dst.exists() else 0
    summary: dict = {
        "audio_key": audio_key,
        "size_bytes": wav_size,
        "sample_rate": settings.audio_sample_rate,
    }

    # Produce a compressed M4A (AAC 96 kbps) when STT_PROVIDER=openai and the
    # WAV file would exceed OpenAI's 25 MB upload limit.  The key is recorded
    # in the summary so that transcribe.py can prefer it over the raw WAV.
    # If compression fails or the output is still too large, the stage fails
    # here with a clear error — no silent fallback to a file that would be
    # rejected by the API anyway.
    if settings.stt_provider.lower() == "openai" and wav_size > _OPENAI_SAFE_BYTES:
        _m4a_timeout = max(60.0, _duration * 0.6)
        m4a_key = f"sessions/{session.id}/audio_openai.m4a"
        m4a_dst = storage.local_path(m4a_key)

        log.info(
            "extract_audio: WAV is %.1f MB — compressing to M4A for OpenAI STT "
            "(timeout %.0fs)",
            wav_size / 1024 / 1024,
            _m4a_timeout,
        )

        m4a_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-i", str(dst),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "aac",
            "-b:a", "96k",
            str(m4a_dst),
        ]
        await common.run_ffmpeg(
            m4a_cmd,
            timeout_sec=_m4a_timeout,
            cleanup_paths=[m4a_dst],
            error_prefix="ffmpeg m4a compression",
        )

        m4a_size = m4a_dst.stat().st_size if m4a_dst.exists() else 0
        if m4a_size == 0 or m4a_size > _OPENAI_SAFE_BYTES:
            if m4a_dst.exists():
                m4a_dst.unlink()
            raise common.FfmpegError(
                f"M4A compression produced an unusable file for OpenAI STT: "
                f"{m4a_size / 1024 / 1024:.1f} MB "
                f"(limit {_OPENAI_SAFE_BYTES // (1024 * 1024)} MB). "
                f"Video duration: {_duration:.0f}s. "
                f"Consider reducing video length or lowering the bitrate."
            )

        summary["audio_openai_key"] = m4a_key
        summary["compressed_size_bytes"] = m4a_size
        summary["compressed_format"] = "m4a_aac_96k"
        log.info(
            "extract_audio: M4A ready — %.1f MB (WAV: %.1f MB, duration: %.0fs)",
            m4a_size / 1024 / 1024,
            wav_size / 1024 / 1024,
            _duration,
        )

    await common.record_stage(db, session, stage="extract_audio", summary=summary)
