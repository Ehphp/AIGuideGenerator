"""Postgres-backed mini job queue.

Uses `SELECT ... FOR UPDATE SKIP LOCKED` for safe concurrent claiming.
This module is the swap boundary for a future Redis/Celery/SQS implementation —
keep it small.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


async def enqueue(
    db: AsyncSession,
    *,
    type: str,
    session_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> Job:
    job = Job(
        type=type,
        session_id=session_id,
        status="pending",
        payload=payload or {},
    )
    db.add(job)
    await db.flush()
    return job


async def claim_one(db: AsyncSession) -> Job | None:
    """Atomically claim the oldest pending job. Returns None if queue is empty.

    Caller is responsible for committing the surrounding transaction.
    """
    stmt = (
        select(Job)
        .where(Job.status == "pending")
        .order_by(Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.flush()
    return job


async def mark_succeeded(db: AsyncSession, job: Job) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(timezone.utc)
    await db.flush()


async def mark_failed(db: AsyncSession, job: Job, error: str) -> None:
    job.status = "failed"
    job.error = error[:4000]
    job.finished_at = datetime.now(timezone.utc)
    await db.flush()
