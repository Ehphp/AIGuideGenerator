"""Stage: extract_audio. ffmpeg -> 16kHz mono wav."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage

log = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


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
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="ignore")
        raise FfmpegError(f"ffmpeg extract_audio failed ({proc.returncode}): {msg}")

    summary = {
        "audio_key": audio_key,
        "size_bytes": dst.stat().st_size if dst.exists() else 0,
        "sample_rate": settings.audio_sample_rate,
    }
    await common.record_stage(db, session, stage="extract_audio", summary=summary)
