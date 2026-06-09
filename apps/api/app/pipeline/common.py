"""Helpers shared by pipeline stages: artifact paths, AI usage accounting."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.services import session_service
from app.storage.local import get_storage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ffmpeg subprocess helper (used by extract_audio, extract_frames, and future
# stages that invoke ffmpeg).  Centralised here to avoid duplicating timeout /
# kill / cleanup logic across stage modules.
# ---------------------------------------------------------------------------


class FfmpegError(RuntimeError):
    """Raised when an ffmpeg subprocess fails or times out."""


async def run_ffmpeg(
    cmd: list[str],
    *,
    timeout_sec: float,
    cleanup_paths: list[Path] | None = None,
    error_prefix: str = "ffmpeg",
) -> bytes:
    """Run an ffmpeg command with timeout, kill-on-timeout, and cleanup.

    Parameters
    ----------
    cmd:
        Full argv list for the ffmpeg process.
    timeout_sec:
        Maximum seconds to wait for the process to finish.
    cleanup_paths:
        Files or directories to remove if the run fails or times out.
        Files are unlinked; directories are removed with shutil.rmtree.
        Ignored on success — callers are responsible for their own output.
    error_prefix:
        Label prepended to error messages (e.g. "ffmpeg scene-detect").

    Returns
    -------
    bytes
        Raw stderr bytes from the process.  Callers that need to parse
        ffmpeg showinfo output (e.g. ``pts_time``) can use this directly.
        Callers that do not need it can discard the return value.

    Raises
    ------
    FfmpegError
        On non-zero exit code or timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        _ffmpeg_cleanup(cleanup_paths)
        raise FfmpegError(
            f"{error_prefix} timed out after {timeout_sec:.0f}s"
        )

    if proc.returncode != 0:
        msg = stderr_bytes.decode(errors="ignore")
        _ffmpeg_cleanup(cleanup_paths)
        raise FfmpegError(f"{error_prefix} failed ({proc.returncode}): {msg}")

    return stderr_bytes


def _ffmpeg_cleanup(paths: list[Path] | None) -> None:
    """Remove partial output files or directories after a failed ffmpeg run."""
    if not paths:
        return
    for p in paths:
        if p is None:
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public-artifact filtering (Phase A).
#
# `Session.pipeline_artifacts` is a JSONB column persisted from each stage's
# summary. When using the OpenAI Vision fallback (`OCR_PROVIDER=openai`), the
# legacy `analyze_frames` stage summary embeds raw OCR / UI text that may
# contain PII. With the default local path (`ocr_frames_local`) the summary
# stores only counts and paths — no raw text. Either way, the API surface
# MUST only expose a
# scrubbed view of this column. The filter is intentionally allowlist-based
# (unknown stage keys are dropped) and recursively strips well-known
# sensitive field names plus anything matching the redaction-map hint.
# ---------------------------------------------------------------------------


PUBLIC_STAGE_KEYS: frozenset[str] = frozenset(
    {
        # Legacy / current pipeline.
        "ingest",
        "extract_audio",
        "transcribe",
        "extract_frames",
        "analyze_frames",
        "build_timeline",
        "generate_guide",
        "validate_guide",
        # New pipeline (Phase C–E).
        "transcribe_local",
        "ocr_frames_local",
        "build_raw_timeline",
        "sanitize_timeline",
        "rehydrate_guide",
        "validate_placeholder_guide",
        # Phase F.
        "attach_evidence",
        # Phase G: egress audit artifacts (public summary only — payload scrubbed).
        "egress_generate_guide",
        "egress_validate_repair",
        # Phase H: grounding audit (aggregate metrics only; full report on disk).
        "grounding_validator",
        # Phase I: visual facts extraction (per-frame structured UI data).
        "extract_visual_facts",
        # Diagnostic: derived per-frame screen view (parse_screens.json).
        "parse_screens",
        # Adaptive pipeline: content classification + routing.
        "classify_content",
        # Two-pass generation: action mining (pass 1) + egress audit.
        "extract_actions",
        "egress_extract_actions",
    }
)


# Field names whose values are scrubbed wherever they appear inside a stage
# summary tree. These are fields known to carry raw text from transcripts,
# OCR, or vision summaries.
SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {"ocr_text", "ui_summary", "raw", "raw_text", "payload"}
)


REDACTION_MAP_HINT = "redaction_map"


def public_artifacts(artifacts: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of the artifacts dict safe to expose over the API.

    - Drops any stage key not in `PUBLIC_STAGE_KEYS`.
    - Drops any key whose name contains the redaction-map hint.
    - Recursively scrubs `SENSITIVE_FIELD_NAMES` from nested dicts/lists.
    - Never mutates the input.
    """
    if not artifacts:
        return {}
    out: dict[str, Any] = {}
    for stage, value in artifacts.items():
        if not isinstance(stage, str):
            continue
        if stage not in PUBLIC_STAGE_KEYS:
            continue
        if REDACTION_MAP_HINT in stage.lower():
            continue
        out[stage] = _scrub(value)
    return out


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                lk = k.lower()
                if k in SENSITIVE_FIELD_NAMES or REDACTION_MAP_HINT in lk:
                    continue
            result[k] = _scrub(v)
        return result
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def session_dir(session_id) -> Path:
    storage = get_storage()
    return storage.local_path(f"sessions/{session_id}")


def artifact_path(session_id, stage: str) -> Path:
    """Full payload path on disk: sessions/<id>/artifacts/<stage>.json"""
    base = session_dir(session_id) / "artifacts"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{stage}.json"


def artifact_storage_key(session_id, stage: str) -> str:
    return f"sessions/{session_id}/artifacts/{stage}.json"


def write_artifact(session_id, stage: str, payload: Any) -> str:
    path = artifact_path(session_id, stage)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return artifact_storage_key(session_id, stage)


def read_artifact(session_id, stage: str) -> Any | None:
    path = artifact_path(session_id, stage)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def stage_done(session: Session, stage: str) -> bool:
    return bool((session.pipeline_artifacts or {}).get(stage))


async def record_stage(
    db: AsyncSession,
    session: Session,
    *,
    stage: str,
    summary: dict[str, Any],
    message: str | None = None,
) -> None:
    await session_service.update_pipeline_artifact(db, session, stage, summary)
    await session_service.append_pipeline_event(
        db, session, stage=stage, level="info", message=message or f"{stage} complete"
    )


async def add_ai_call(
    db: AsyncSession,
    session: Session,
    *,
    stage: str,
    model: str,
    input_chars: int = 0,
    output_chars: int = 0,
    audio_duration_sec: float | None = None,
    frame_count: int | None = None,
) -> None:
    usage = dict(session.ai_usage or {})
    models = dict(usage.get("models") or {})
    if stage in {"transcribe"}:
        models["stt"] = model
    elif stage in {"analyze_frames"}:
        models["vision"] = model
    elif stage in {"generate_guide", "validate_guide"}:
        models["llm"] = model
    usage["models"] = models

    if audio_duration_sec is not None:
        usage["audio_duration_sec"] = float(audio_duration_sec)
    if frame_count is not None:
        usage["frame_count"] = int(frame_count)

    usage["approx_input_chars"] = int(usage.get("approx_input_chars", 0)) + int(
        input_chars
    )

    calls = list(usage.get("calls") or [])
    calls.append(
        {
            "stage": stage,
            "model": model,
            "input_chars": int(input_chars),
            "output_chars": int(output_chars),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    usage["calls"] = calls

    session.ai_usage = usage
    await db.flush()
