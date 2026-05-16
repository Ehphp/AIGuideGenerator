"""Stage: sanitize_timeline (Phase E).

Reads the raw `build_timeline` artifact, runs the deterministic sanitizer,
and writes:

- `sanitize_timeline.json` — the sanitized timeline (placeholders only).
  This is the artifact that may cross the external-LLM boundary.
- `redaction_map.local.json` — placeholder→original mapping. **Local-only**
  (file mode 0o600 best-effort); never exposed by the API surface.

DB summary stores **counts only** (no map content, no values).
"""
from __future__ import annotations

import json
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.pipeline import common
from app.pipeline.internal_tool_filter import filter_internal_tool_noise_from_timeline
from app.sanitize import Sanitizer

log = logging.getLogger(__name__)


REDACTION_MAP_STAGE = "redaction_map.local"


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "sanitize_timeline"):
        return

    timeline = common.read_artifact(session.id, "build_timeline")
    if not timeline:
        raise RuntimeError("sanitize_timeline requires build_timeline to have run")

    # Strip the continuous leading block of Guide Generator self-referential
    # events *before* the sanitizer and *before* the LLM boundary.
    # build_timeline.json is left untouched for debugging.
    filtered = filter_internal_tool_noise_from_timeline(timeline)
    dropped = filtered["internal_tool_filter"]["dropped_prefix_events"]
    if dropped:
        log.info(
            "sanitize_timeline: dropped %d leading internal-tool-noise event(s) "
            "(session=%s)",
            dropped,
            session.id,
        )

    sanitizer = Sanitizer()
    result = sanitizer.sanitize_timeline(filtered)

    common.write_artifact(session.id, "sanitize_timeline", result.sanitized)

    map_path = common.artifact_path(session.id, REDACTION_MAP_STAGE)
    map_path.write_text(
        json.dumps(result.redaction_map, ensure_ascii=False, indent=2)
    )
    # Best-effort restrictive perms (no-op on Windows).
    try:
        os.chmod(map_path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        log.debug("chmod 0o600 failed for redaction map (non-POSIX?)")

    summary = {
        "path": common.artifact_storage_key(session.id, "sanitize_timeline"),
        "event_count": result.report["events_total"],
        "events_modified": result.report["events_modified"],
        "placeholder_count": result.report["placeholders_total"],
        "distinct_values": result.report["distinct_values"],
        "categories": result.report["categories"],
        "redaction_map_present": True,
        "dropped_prefix_events": dropped,
    }
    await common.record_stage(db, session, stage="sanitize_timeline", summary=summary)
