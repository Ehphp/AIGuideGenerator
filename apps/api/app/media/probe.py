"""ffprobe wrapper used at upload time to populate media metadata."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class MediaProbe:
    duration_sec: float | None
    has_audio: bool
    width: int | None
    height: int | None


async def probe_media(path: Path) -> MediaProbe:
    """Run `ffprobe -show_format -show_streams -of json` against `path`.

    Returns best-effort metadata; on failure returns all-Nones rather than raising,
    since metadata is informational at this stage.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("ffprobe failed (%s): %s", proc.returncode, stderr.decode(errors="ignore"))
            return MediaProbe(None, False, None, None)
        data = json.loads(stdout or b"{}")
    except FileNotFoundError:
        log.warning("ffprobe not installed; skipping media probe")
        return MediaProbe(None, False, None, None)
    except Exception:
        log.exception("ffprobe error")
        return MediaProbe(None, False, None, None)

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    duration: float | None = None
    try:
        duration = float(fmt.get("duration")) if fmt.get("duration") else None
    except (TypeError, ValueError):
        duration = None

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    width = int(video["width"]) if video and "width" in video else None
    height = int(video["height"]) if video and "height" in video else None

    return MediaProbe(duration_sec=duration, has_audio=has_audio, width=width, height=height)
