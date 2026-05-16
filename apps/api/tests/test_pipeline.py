"""Pipeline tests using FakeAIProvider, no network calls.

These tests exercise: extract_audio (real ffmpeg), transcribe (fake),
extract_frames (real ffmpeg + phash), analyze_frames (fake), and the
end-to-end orchestrator. Skipped if ffmpeg is missing.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.config import settings


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


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
    pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg/ffprobe not installed"),
    pytest.mark.skipif(not _postgres_reachable(), reason="Postgres not reachable"),
]


async def _make_synthetic_video(dst: Path, seconds: int = 4) -> None:
    """Generate a small video with audio using ffmpeg lavfi sources."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Combine smptebars (changing colors) + 440Hz tone.
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
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
        raise RuntimeError(f"failed to synthesize test video: {stderr.decode(errors='ignore')}")


@pytest.mark.asyncio
async def test_pipeline_end_to_end_with_fake_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "fake")
    # Re-import settings is heavy; instead patch the live object.
    from app import config as cfg
    cfg.settings.ai_provider = "fake"

    # Lazy imports to ensure settings patch is in effect.
    from app.db import SessionLocal, engine
    from app.models.session import Session
    from app.pipeline import orchestrator
    from app.services import session_service
    from app.storage.local import get_storage

    storage = get_storage()
    sid = uuid.uuid4()
    media_key = f"sessions/{sid}/original.webm"
    media_path = storage.local_path(media_key)
    await _make_synthetic_video(media_path, seconds=4)

    try:
        # Create and commit the session so orchestrator.run() can find it.
        async with SessionLocal() as db:
            async with db.begin():
                s = Session(
                    title="pipeline-test",
                    source_type="uploaded",
                    status="created",
                )
                db.add(s)
                await db.flush()
                await session_service.attach_media(
                    db,
                    s,
                    media_key=media_key,
                    media_mime="video/webm",
                    media_size_bytes=media_path.stat().st_size,
                    media_duration_sec=None,
                )
                await session_service.transition_status(
                    db, s, "processing", progress_message="test"
                )
                sid_db = s.id

        # Run the pipeline — each stage manages its own transaction.
        await orchestrator.run(sid_db)

        # Re-load and assert.
        async with SessionLocal() as db:
            s2 = await session_service.get_session(db, sid_db)
            assert s2.status == "ready"
            artifacts = s2.pipeline_artifacts or {}
            assert "ingest" in artifacts
            assert "extract_audio" in artifacts
            assert "transcribe" in artifacts
            assert "extract_frames" in artifacts
            assert "analyze_frames" in artifacts
            assert "build_timeline" in artifacts
            assert "generate_guide" in artifacts
            assert "validate_guide" in artifacts
            frames = artifacts["extract_frames"]
            assert isinstance(frames, list) and len(frames) >= 1
            analyzed = artifacts["analyze_frames"]
            assert len(analyzed) == len(frames)
            usage = s2.ai_usage or {}
            assert usage.get("frame_count") == len(frames)
            assert "calls" in usage and len(usage["calls"]) >= 2
            # Phase 4 assertions.
            assert s2.guide_schema_version == "1.0"
            assert isinstance(s2.guide_content, dict)
            assert s2.guide_content.get("schema_version") == "1.0"
            steps = s2.guide_content.get("steps") or []
            assert len(steps) >= 1
            assert steps[0].get("id") == "step-1"
    finally:
        await engine.dispose()
        # Cleanup files.
        try:
            shutil_root = storage.local_path(f"sessions/{sid}")
            shutil.rmtree(shutil_root, ignore_errors=True)
        except Exception:
            pass
