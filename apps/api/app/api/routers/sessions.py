"""Sessions router: CRUD + media upload + retry."""
from __future__ import annotations

import mimetypes
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session as get_db
from app.jobs import queue
from app.media.probe import probe_media
from app.schemas.job import JobRead
from app.schemas.session import SessionCreate, SessionGuideUpdate, SessionRead
from app.schemas.guide import Guide as GuideContent
from app.services import session_service
from app.services.guide_export import guide_to_docx, safe_filename
from app.storage.local import get_storage

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

_MAX_BYTES = settings.max_recording_mb * 1024 * 1024
_CHUNK = 1024 * 1024  # 1 MiB


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, db: AsyncSession = Depends(get_db)) -> SessionRead:
    s = await session_service.create_session(
        db, title=payload.title, source_type=payload.source_type
    )
    await db.commit()
    await db.refresh(s)
    return SessionRead.model_validate(s)


@router.get("", response_model=list[SessionRead])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[SessionRead]:
    items = await session_service.list_sessions(db)
    return [SessionRead.model_validate(i) for i in items]


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> SessionRead:
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionRead.model_validate(s)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")
    storage = get_storage()
    await storage.delete_prefix(f"sessions/{session_id}")
    await db.delete(s)
    await db.commit()


@router.post("/{session_id}/media", response_model=SessionRead)
async def upload_media(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> SessionRead:
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")

    if s.status != "created":
        raise HTTPException(status_code=409, detail=f"cannot upload media in status {s.status!r}")

    mime_full = (file.content_type or "").lower()
    # Strip parameters like ";codecs=vp9,opus" before whitelisting.
    mime = mime_full.split(";", 1)[0].strip()
    if mime not in settings.allowed_mimes_set:
        raise HTTPException(status_code=415, detail=f"unsupported media type: {mime_full!r}")

    ext = (mimetypes.guess_extension(mime) or ".bin").lstrip(".")
    if mime == "video/quicktime":
        ext = "mov"
    elif mime == "video/x-matroska":
        ext = "mkv"
    key = f"sessions/{session_id}/original.{ext}"

    storage = get_storage()

    # Stream to storage with a hard size cap.
    written = 0

    async def _chunks():
        nonlocal written
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"file exceeds {settings.max_recording_mb} MB limit",
                )
            yield chunk

    try:
        total = await storage.save_stream(key, _chunks())
    except HTTPException:
        await storage.delete_prefix(key)
        raise

    # Probe metadata (best-effort).
    probe = await probe_media(storage.local_path(key))

    await session_service.attach_media(
        db,
        s,
        media_key=key,
        media_mime=mime,
        media_size_bytes=total,
        media_duration_sec=probe.duration_sec,
    )
    await queue.enqueue(db, type="process_recording", session_id=s.id)
    await db.commit()
    await db.refresh(s)
    return SessionRead.model_validate(s)


@router.post("/{session_id}/retry", response_model=JobRead)
async def retry_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobRead:
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")
    if s.status != "failed":
        raise HTTPException(
            status_code=409, detail=f"can only retry failed sessions (current: {s.status!r})"
        )
    try:
        await session_service.transition_status(
            db, s, "processing", progress_message="Retrying"
        )
    except session_service.InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    job = await queue.enqueue(db, type="process_recording", session_id=s.id)
    await db.commit()
    await db.refresh(job)
    return JobRead.model_validate(job)


@router.post("/{session_id}/reprocess", response_model=JobRead)
async def reprocess_session(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> JobRead:
    """Force a full pipeline re-run on an already-processed session.

    Wipes prior artifacts (DB + on-disk) and re-enqueues a `process_recording`
    job. Allowed for sessions in `ready` or `failed`. The uploaded media is
    preserved.
    """
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")
    if s.status not in ("ready", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"can only reprocess ready/failed sessions (current: {s.status!r})",
        )
    if not s.media_key:
        raise HTTPException(status_code=409, detail="session has no uploaded media")

    await session_service.reset_pipeline_state(db, s)
    try:
        await session_service.transition_status(
            db, s, "processing", progress_message="Reprocessing"
        )
    except session_service.InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    job = await queue.enqueue(db, type="process_recording", session_id=s.id)
    await db.commit()
    await db.refresh(job)
    return JobRead.model_validate(job)


@router.patch("/{session_id}/guide", response_model=SessionRead)
async def update_guide(
    session_id: uuid.UUID,
    payload: SessionGuideUpdate,
    db: AsyncSession = Depends(get_db),
) -> SessionRead:
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")

    if s.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"can only edit guide of ready sessions (current: {s.status!r})",
        )

    s = await session_service.update_guide_content(
        db, s, payload.guide.model_dump()
    )
    await db.commit()
    await db.refresh(s)
    return SessionRead.model_validate(s)


_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.get("/{session_id}/export.docx")
async def export_guide_docx(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Response:
    """Download the current guide as a Word document (.docx).

    Returns 404 when the session does not exist and 422 when the session has
    no guide yet (pipeline not complete or not yet run).
    """
    try:
        s = await session_service.get_session(db, session_id)
    except session_service.SessionNotFound:
        raise HTTPException(status_code=404, detail="session not found")

    if not s.guide_content:
        raise HTTPException(
            status_code=422,
            detail="guide not available — pipeline has not completed for this session",
        )

    try:
        guide = GuideContent.model_validate(s.guide_content)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=422, detail=f"guide content is invalid: {exc}"
        ) from exc

    docx_bytes = guide_to_docx(guide, session_id)
    filename = safe_filename(guide.title, session_id)
    # Sanitise filename for Content-Disposition header (ASCII printable only).
    ascii_filename = re.sub(r"[^\x20-\x7e]", "_", filename)

    return Response(
        content=docx_bytes,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"',
        },
    )
