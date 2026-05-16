from __future__ import annotations

import socket

import pytest
from urllib.parse import urlparse

from app.config import settings


def _postgres_reachable() -> bool:
    url = urlparse(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    if not url.hostname:
        return False
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_reachable(), reason="Postgres not reachable"),
]


@pytest.mark.asyncio
async def test_persist_progress_message_is_visible_across_sessions() -> None:
    from app.db import SessionLocal, engine
    from app.models.session import Session
    from app.services import session_service

    sid_db = None
    try:
        async with SessionLocal() as db:
            async with db.begin():
                s = Session(
                    title="progress-visibility-test",
                    source_type="uploaded",
                    status="processing",
                    progress_message="Pipeline starting",
                )
                db.add(s)
                await db.flush()
                sid_db = s.id

        async with SessionLocal() as db:
            async with db.begin():
                s = await session_service.get_session(db, sid_db)

                await session_service.persist_progress_message(s.id, "Transcribing")

                async with SessionLocal() as reader:
                    visible = await session_service.get_session(reader, s.id)
                    assert visible.progress_message == "Transcribing"

                s.progress_message = "Pipeline starting"

        async with SessionLocal() as db:
            reloaded = await session_service.get_session(db, sid_db)
            assert reloaded.progress_message == "Transcribing"
    finally:
        await engine.dispose()