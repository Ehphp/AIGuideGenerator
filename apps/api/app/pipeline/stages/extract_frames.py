"""Stage: extract_frames.

Two-pass extraction:
  1. Scene-detect frames via ffmpeg `select=gt(scene,THRESH)`.
  2. Uniform sampling every N seconds.
Then perceptual-hash dedup, capped at MAX_FRAMES.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

import imagehash
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage

log = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


async def _ffmpeg_extract_scene(src: Path, out_dir: Path, threshold: float) -> list[tuple[float, Path]]:
    """Returns list of (timestamp_sec, path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "scene_%05d.jpg")
    # Use showinfo to capture pts_time per frame.
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "info",
        "-i", str(src),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr",
        "-q:v", "3",
        pattern,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="ignore")
        raise FfmpegError(f"ffmpeg scene-detect failed ({proc.returncode}): {msg}")

    # Parse pts_time:N.NNN from showinfo lines.
    times: list[float] = []
    for m in re.finditer(rb"pts_time:([0-9.]+)", stderr):
        try:
            times.append(float(m.group(1)))
        except ValueError:
            pass

    files = sorted(out_dir.glob("scene_*.jpg"))
    pairs: list[tuple[float, Path]] = []
    for i, f in enumerate(files):
        t = times[i] if i < len(times) else float(i)
        pairs.append((t, f))
    return pairs


async def _ffmpeg_extract_uniform(
    src: Path, out_dir: Path, interval_sec: float
) -> list[tuple[float, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "u_%05d.jpg")
    fps = 1.0 / max(interval_sec, 0.1)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", str(src),
        "-vf", f"fps={fps}",
        "-q:v", "3",
        pattern,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="ignore")
        raise FfmpegError(f"ffmpeg uniform sampling failed ({proc.returncode}): {msg}")
    files = sorted(out_dir.glob("u_*.jpg"))
    return [(i * interval_sec, f) for i, f in enumerate(files)]


def _phash_dedup(
    pairs: list[tuple[float, Path]], max_distance: int
) -> list[tuple[float, Path]]:
    """Greedy dedup: keep a frame only if its phash is at distance > max_distance from all kept."""
    kept: list[tuple[float, Path, imagehash.ImageHash]] = []
    for t, p in pairs:
        try:
            h = imagehash.phash(Image.open(p))
        except Exception:
            log.warning("phash failed for %s, skipping", p)
            continue
        too_close = False
        for _, _, kh in kept:
            if abs(h - kh) <= max_distance:
                too_close = True
                break
        if not too_close:
            kept.append((t, p, h))
    return [(t, p) for (t, p, _) in kept]


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "extract_frames"):
        return
    if not session.media_key:
        raise RuntimeError("session has no media_key")

    storage = get_storage()
    src = storage.local_path(session.media_key)
    work_root = common.session_dir(session.id) / "frames_work"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)

    scene_dir = work_root / "scene"
    uniform_dir = work_root / "uniform"

    scene_pairs: list[tuple[float, Path]] = []
    try:
        scene_pairs = await _ffmpeg_extract_scene(
            src, scene_dir, settings.frames_scene_threshold
        )
    except FfmpegError as e:
        log.warning("scene-detect failed, continuing with uniform only: %s", e)

    uniform_pairs = await _ffmpeg_extract_uniform(
        src, uniform_dir, settings.frames_uniform_interval_sec
    )

    # Merge & sort by timestamp.
    merged = sorted(scene_pairs + uniform_pairs, key=lambda x: x[0])
    deduped = _phash_dedup(merged, settings.frames_phash_distance)
    capped = deduped[: settings.max_frames]

    # Move kept frames into final location with stable names.
    final_dir = common.session_dir(session.id) / "frames"
    if final_dir.exists():
        shutil.rmtree(final_dir, ignore_errors=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    final_frames: list[dict] = []
    for idx, (t, src_path) in enumerate(capped):
        name = f"frame_{idx:04d}.jpg"
        dst = final_dir / name
        shutil.copyfile(src_path, dst)
        key = f"sessions/{session.id}/frames/{name}"
        final_frames.append({"idx": idx, "t": float(t), "key": key})

    # Cleanup work dir.
    shutil.rmtree(work_root, ignore_errors=True)

    summary = final_frames  # array of {idx,t,key}
    await common.record_stage(
        db,
        session,
        stage="extract_frames",
        summary=summary,
        message=f"extracted {len(final_frames)} frames",
    )
