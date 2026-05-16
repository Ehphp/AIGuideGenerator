"""Worker entrypoint: claims jobs from the Postgres queue and dispatches handlers."""
from __future__ import annotations

import asyncio
import logging
import traceback

from app.config import settings
from app.db import SessionLocal, create_all
from app.jobs import queue
from app.jobs.handlers import HANDLERS
from app.logging_filters import install_redaction_map_filter
from app.services import session_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Attach the redaction-map filter AFTER basicConfig so it can wrap the
# StreamHandler installed by basicConfig.
install_redaction_map_filter()

log = logging.getLogger("worker")


async def _process_one() -> bool:
    """Claim and process one job. Returns True if a job was processed."""
    async with SessionLocal() as db:
        async with db.begin():
            job = await queue.claim_one(db)
        if job is None:
            return False

        handler = HANDLERS.get(job.type)
        if handler is None:
            async with db.begin():
                await queue.mark_failed(db, job, f"no handler for type {job.type!r}")
            log.error("no handler for job type %s", job.type)
            return True

        # Cache scalar attributes before entering try/except so they're available
        # even if the ORM session expires after a rollback (avoids MissingGreenlet).
        job_id = job.id
        job_type = job.type
        job_session_id = job.session_id

        try:
            async with db.begin():
                await handler(db, job)
                await queue.mark_succeeded(db, job)
            log.info("job %s (%s) succeeded", job_id, job_type)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            async with db.begin():
                from app.models.job import Job as JobModel

                fresh = await db.get(JobModel, job_id)
                if fresh is not None:
                    await queue.mark_failed(
                        db,
                        fresh,
                        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    )
                if job_session_id is not None:
                    try:
                        s = await session_service.get_session(db, job_session_id)
                        if s.status in {"uploaded", "processing"}:
                            await session_service.transition_status(
                                db, s, "failed", error=str(exc)
                            )
                    except Exception:
                        log.exception(
                            "failed to mark session failed for job %s", job_id
                        )
        return True


async def main() -> None:
    log.info("worker starting; poll interval %.1fs", settings.worker_poll_interval_sec)
    await create_all()
    while True:
        try:
            had_work = await _process_one()
        except Exception:
            log.exception("worker loop error")
            had_work = False
        if not had_work:
            await asyncio.sleep(settings.worker_poll_interval_sec)


if __name__ == "__main__":
    asyncio.run(main())
