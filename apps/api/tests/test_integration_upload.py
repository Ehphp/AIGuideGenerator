"""End-to-end integration test: create session -> upload -> process via worker handler.

Runs entirely inside one asyncio event loop using httpx ASGITransport + asgi-lifespan,
to avoid the "Future attached to a different loop" problem with the async DB pool.

Skipped automatically if Postgres or ffmpeg is not available.
"""
from __future__ import annotations

import asyncio
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app import config as cfg
from app.config import settings
from app.db import SessionLocal, engine
from app.jobs import queue
from app.jobs.handlers import HANDLERS
from app.main import app


def _postgres_reachable() -> bool:
    url = urlparse(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    if not url.hostname:
        return False
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1.0):
            return True
    except OSError:
        return False


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_reachable(), reason="Postgres not reachable"),
    pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg/ffprobe not installed"),
]


async def _make_synthetic_video(dst: Path, seconds: int = 3) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"smptebars=size=320x180:rate=10:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={seconds}",
        "-c:v", "libvpx", "-b:v", "200k",
        "-c:a", "libopus", "-b:a", "32k",
        "-shortest",
        str(dst),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="ignore"))


@pytest.mark.asyncio
async def test_create_upload_and_process(tmp_path: Path) -> None:
    cfg.settings.ai_provider = "fake"  # avoid network calls

    sample = tmp_path / "sample.webm"
    await _make_synthetic_video(sample, seconds=3)

    transport = ASGITransport(app=app)
    sid: str | None = None
    try:
        async with LifespanManager(app):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/sessions",
                    json={"source_type": "uploaded", "title": "t"},
                )
                assert r.status_code == 201, r.text
                sid = r.json()["id"]

                with sample.open("rb") as fh:
                    r = await client.post(
                        f"/api/v1/sessions/{sid}/media",
                        files={"file": ("sample.webm", fh, "video/webm")},
                    )
                assert r.status_code == 200, r.text
                assert r.json()["status"] == "uploaded"

                # Drive one worker tick directly (same event loop).
                async with SessionLocal() as db:
                    async with db.begin():
                        job = await queue.claim_one(db)
                    assert job is not None
                    async with db.begin():
                        await HANDLERS[job.type](db, job)
                        await queue.mark_succeeded(db, job)

                r = await client.get(f"/api/v1/sessions/{sid}")
                assert r.status_code == 200
                body = r.json()
                assert body["status"] == "ready"

                r = await client.delete(f"/api/v1/sessions/{sid}")
                assert r.status_code == 204
    finally:
        await engine.dispose()

