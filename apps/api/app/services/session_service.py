"""Session service: encapsulates business rules including status-transition guards."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.session import Session
from app.schemas.session import is_transition_allowed


class InvalidStatusTransition(ValueError):
    pass


class SessionNotFound(LookupError):
    pass


async def create_session(
    db: AsyncSession, *, title: str | None, source_type: str
) -> Session:
    s = Session(title=title, source_type=source_type, status="created")
    db.add(s)
    await db.flush()
    return s


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Session:
    s = await db.get(Session, session_id)
    if s is None:
        raise SessionNotFound(str(session_id))
    return s


async def list_sessions(db: AsyncSession) -> list[Session]:
    result = await db.execute(select(Session).order_by(Session.created_at.desc()))
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    s = await get_session(db, session_id)
    await db.delete(s)
    await db.flush()


async def transition_status(
    db: AsyncSession,
    session: Session,
    target: str,
    *,
    progress_message: str | None = None,
    error: str | None = None,
) -> Session:
    if not is_transition_allowed(session.status, target):
        raise InvalidStatusTransition(
            f"cannot transition session {session.id} from {session.status!r} to {target!r}"
        )
    session.status = target
    if progress_message is not None:
        session.progress_message = progress_message
    if target == "failed" and error is not None:
        session.error = error
    if target == "processing":
        session.error = None
    await db.flush()
    return session


async def attach_media(
    db: AsyncSession,
    session: Session,
    *,
    media_key: str,
    media_mime: str,
    media_size_bytes: int,
    media_duration_sec: float | None,
) -> Session:
    session.media_key = media_key
    session.media_mime = media_mime
    session.media_size_bytes = media_size_bytes
    session.media_duration_sec = media_duration_sec
    await transition_status(db, session, "uploaded", progress_message="Uploaded; queued for processing")
    return session


async def update_pipeline_artifact(
    db: AsyncSession, session: Session, key: str, value: Any
) -> None:
    """Replace a single key in `pipeline_artifacts` (JSONB)."""
    artifacts = dict(session.pipeline_artifacts or {})
    artifacts[key] = value
    session.pipeline_artifacts = artifacts
    await db.flush()


async def persist_progress_message(session_id: uuid.UUID, message: str) -> None:
    """Commit a progress update outside the worker's long-running transaction."""
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(
                update(Session)
                .where(Session.id == session_id)
                .values(progress_message=message)
            )


async def reset_pipeline_state(db: AsyncSession, session: Session) -> None:
    """Wipe everything produced by previous pipeline runs for `session`.

    Clears the JSON columns (`pipeline_artifacts`, `pipeline_events`,
    `ai_usage`, `guide_*`, `progress_message`, `error`) **and** removes
    every on-disk artifact file under ``sessions/<id>/artifacts/`` so the
    next run cannot satisfy any stage's idempotency check from a stale
    file. The original media is preserved.
    """
    from app.storage.local import get_storage

    storage = get_storage()
    await storage.delete_prefix(f"sessions/{session.id}/artifacts")

    session.pipeline_artifacts = {}
    session.pipeline_events = []
    session.ai_usage = {}
    session.guide_content = None
    session.guide_schema_version = None
    session.guide_edited_at = None
    session.progress_message = None
    session.error = None
    await db.flush()


async def append_pipeline_event(
    db: AsyncSession, session: Session, *, stage: str, level: str, message: str
) -> None:
    events = list(session.pipeline_events or [])
    events.append(
        {
            "t": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "level": level,
            "message": message,
        }
    )
    session.pipeline_events = events
    await db.flush()


async def update_guide_content(
    db: AsyncSession, session: Session, guide_dict: dict[str, Any]
) -> Session:
    """Persist manually edited guide content for a ready session.

    Keep AI metadata attribution stable across manual edits.
    """
    if session.guide_content and isinstance(session.guide_content, dict):
        original_metadata = session.guide_content.get("metadata")
        if isinstance(original_metadata, dict):
            guide_dict = {**guide_dict, "metadata": original_metadata}

    session.guide_content = guide_dict
    session.guide_edited_at = datetime.now(timezone.utc)
    await db.flush()
    return session
