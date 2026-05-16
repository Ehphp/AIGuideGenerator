"""Stage: ingest. Probes the uploaded media via ffprobe."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.media.probe import probe_media
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "ingest"):
        return
    if not session.media_key:
        raise RuntimeError("session has no media_key")

    media_path = get_storage().local_path(session.media_key)
    probe = await probe_media(media_path)

    summary = {
        "duration": probe.duration_sec,
        "width": probe.width,
        "height": probe.height,
        "has_audio": probe.has_audio,
    }
    # Backfill duration on session if previously unknown.
    if probe.duration_sec and not session.media_duration_sec:
        session.media_duration_sec = probe.duration_sec

    await common.record_stage(db, session, stage="ingest", summary=summary)
