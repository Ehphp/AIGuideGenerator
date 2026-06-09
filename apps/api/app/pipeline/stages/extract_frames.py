"""Stage: extract_frames.

Two-pass extraction:
  1. Scene-detect frames via ffmpeg `select=gt(scene,THRESH)`.
  2. Uniform sampling every N seconds.
Then perceptual-hash dedup, capped at MAX_FRAMES.
"""
from __future__ import annotations

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


async def _ffmpeg_extract_scene(
    src: Path, out_dir: Path, threshold: float, timeout_sec: float
) -> list[tuple[float, Path]]:
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
    stderr_bytes = await common.run_ffmpeg(
        cmd,
        timeout_sec=timeout_sec,
        cleanup_paths=[out_dir],
        error_prefix="ffmpeg scene-detect",
    )

    # Parse pts_time:N.NNN from showinfo lines.
    times: list[float] = []
    for m in re.finditer(rb"pts_time:([0-9.]+)", stderr_bytes):
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
    src: Path, out_dir: Path, interval_sec: float, timeout_sec: float
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
    await common.run_ffmpeg(
        cmd,
        timeout_sec=timeout_sec,
        cleanup_paths=[out_dir],
        error_prefix="ffmpeg uniform-sampling",
    )
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

    # Timeout: at least 5 min, or 2.5× the recorded duration (same as extract_audio).
    # Applied independently to each ffmpeg pass.
    _duration = session.media_duration_sec or 1200.0
    _ffmpeg_timeout = max(300.0, _duration * 2.5)

    scene_dir = work_root / "scene"
    uniform_dir = work_root / "uniform"

    final_frames: list[dict] = []
    _count_raw_scene = 0
    _count_raw_uniform = 0
    _count_after_dedup = 0
    try:
        scene_pairs: list[tuple[float, Path]] = []
        try:
            scene_pairs = await _ffmpeg_extract_scene(
                src, scene_dir, settings.frames_scene_threshold, _ffmpeg_timeout
            )
        except common.FfmpegError as e:
            log.warning("scene-detect failed, continuing with uniform only: %s", e)
        _count_raw_scene = len(scene_pairs)

        uniform_pairs = await _ffmpeg_extract_uniform(
            src, uniform_dir, settings.frames_uniform_interval_sec, _ffmpeg_timeout
        )
        _count_raw_uniform = len(uniform_pairs)

        # Merge & sort by timestamp.
        merged = sorted(scene_pairs + uniform_pairs, key=lambda x: x[0])
        deduped = _phash_dedup(merged, settings.frames_phash_distance)
        _count_after_dedup = len(deduped)
        capped = deduped[: settings.max_frames]

        # Move kept frames into final location with stable names.
        final_dir = common.session_dir(session.id) / "frames"
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        for idx, (t, src_path) in enumerate(capped):
            name = f"frame_{idx:04d}.jpg"
            dst = final_dir / name
            shutil.copyfile(src_path, dst)
            key = f"sessions/{session.id}/frames/{name}"
            final_frames.append({"idx": idx, "t": float(t), "key": key})

    finally:
        # Always clean up the temporary working directory, whether we succeeded
        # or failed.  On success the frames have already been copied to final_dir.
        shutil.rmtree(work_root, ignore_errors=True)

    _times = [f["t"] for f in final_frames]
    _gaps = (
        [_times[i + 1] - _times[i] for i in range(len(_times) - 1)]
        if len(_times) >= 2
        else []
    )
    summary: dict = {
        "frames": final_frames,
        "frame_count_raw_scene": _count_raw_scene,
        "frame_count_raw_uniform": _count_raw_uniform,
        "frame_count_after_dedup": _count_after_dedup,
        "frame_count_final": len(final_frames),
        "frame_t_min": _times[0] if _times else None,
        "frame_t_max": _times[-1] if _times else None,
        "frame_max_gap_sec": max(_gaps) if _gaps else None,
        "frame_mean_gap_sec": sum(_gaps) / len(_gaps) if _gaps else None,
    }
    await common.record_stage(
        db,
        session,
        stage="extract_frames",
        summary=summary,
        message=f"extracted {len(final_frames)} frames",
    )
