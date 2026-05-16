"""Job handlers."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.job import Job
from app.pipeline import orchestrator
from app.services import session_service

log = logging.getLogger("worker.handlers")


async def handle_process_recording(db: AsyncSession, job: Job) -> None:
    if job.session_id is None:
        raise ValueError("process_recording job has no session_id")

    # Transition status in its own committed transaction so the UI sees
    # "processing" immediately, without waiting for the whole pipeline.
    async with SessionLocal() as own_db:
        async with own_db.begin():
            s = await session_service.get_session(own_db, job.session_id)
            if s.status == "uploaded":
                await session_service.transition_status(
                    own_db, s, "processing", progress_message="Pipeline starting"
                )
            elif s.status == "failed":
                await session_service.transition_status(
                    own_db, s, "processing", progress_message="Retry: pipeline starting"
                )
            elif s.status != "processing":
                raise ValueError(
                    f"unexpected session status for processing: {s.status!r}"
                )

    # Run the pipeline — each stage manages its own transaction.
    await orchestrator.run(job.session_id)
    log.info("process_recording completed for session %s", job.session_id)


HANDLERS = {
    "process_recording": handle_process_recording,
}

