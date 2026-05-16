"""Stage: rehydrate_guide (Phase E).

Replaces `[CATEGORY_N]` placeholders in the LLM-generated guide text with
the original values from the local redaction map. Runs entirely on the
host; no external calls.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.pipeline import common
from app.pipeline.stages.sanitize_timeline import REDACTION_MAP_STAGE
from app.sanitize import rehydrate_text

log = logging.getLogger(__name__)


def _load_redaction_map(session_id) -> dict[str, str]:
    path = common.artifact_path(session_id, REDACTION_MAP_STAGE)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "rehydrate_guide"):
        return

    gen = common.read_artifact(session.id, "generate_guide")
    if not gen or "raw_text" not in gen:
        raise RuntimeError("rehydrate_guide requires generate_guide to have run")

    redaction_map = _load_redaction_map(session.id)
    placeholder_text = gen["raw_text"]
    rehydrated_text, stats = rehydrate_text(placeholder_text, redaction_map)

    common.write_artifact(
        session.id,
        "rehydrate_guide",
        {
            "placeholder_text": placeholder_text,
            "raw_text": rehydrated_text,
            "placeholders_resolved": stats.resolved,
            "placeholders_unresolved": stats.unresolved,
            "unresolved_placeholders": stats.unresolved_placeholders,
        },
    )
    summary = {
        "path": common.artifact_storage_key(session.id, "rehydrate_guide"),
        "placeholders_resolved": stats.resolved,
        "placeholders_unresolved": stats.unresolved,
    }
    await common.record_stage(db, session, stage="rehydrate_guide", summary=summary)

    if stats.unresolved:
        log.warning(
            "rehydrate_guide: %d unresolved placeholders (session=%s)",
            stats.unresolved,
            session.id,
        )
