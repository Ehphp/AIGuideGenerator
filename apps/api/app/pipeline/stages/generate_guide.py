"""Stage: generate_guide. LLM JSON-mode call producing a draft Guide JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.config import settings
from app.models.session import Session
from app.pipeline import common, safety

log = logging.getLogger(__name__)


def _load_prompt() -> str:
    p = Path(__file__).resolve().parent.parent / "prompts" / "guide_generation.md"
    return p.read_text()


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "generate_guide"):
        return

    if settings.sanitize_enabled:
        # Phase E: external LLM may only see the sanitized timeline.
        timeline = safety.read_public_artifact_for_llm(
            session.id, "sanitize_timeline"
        )
        if not timeline:
            raise RuntimeError(
                "generate_guide (sanitize_enabled) requires sanitize_timeline"
            )
        # Belt-and-braces: refuse to send anything that still trips the
        # leak-tripwire detectors. Failure here means the sanitizer missed
        # something — we'd rather fail the run than leak.
        safety.assert_not_raw_artifact(timeline, context="generate_guide")
    else:
        timeline = common.read_artifact(session.id, "build_timeline")
        if not timeline:
            raise RuntimeError("generate_guide requires build_timeline to have run")

    # Prepare the timeline for external egress:
    # - opacify frame_key paths (remove session UUID)
    # - assert no raw PII slipped past sanitizer
    timeline_egress = safety.prepare_for_egress(timeline, context="generate_guide")

    prompt = _load_prompt() + "\n```json\n" + json.dumps(timeline_egress, ensure_ascii=False) + "\n```\n"

    # --- Egress audit artifact -------------------------------------------
    # Exact snapshot of what was sent to the external LLM, saved locally for
    # operator inspection. Never served to the UI in raw form; public_artifacts
    # exposes only a summary (prompt_chars, event counts, flags).
    events = timeline_egress.get("events") or []
    egress_snapshot: dict = {
        "prompt_chars": len(prompt),
        "timeline_language": timeline_egress.get("language"),
        "events_total": len(events),
        "transcript_events": sum(1 for e in events if e.get("kind") == "transcript"),
        "frame_events": sum(1 for e in events if e.get("kind") == "frame"),
        "sanitize_enabled": settings.sanitize_enabled,
        "ocr_provider": settings.ocr_provider,
        "frame_keys_opacified": True,
        "payload": timeline_egress,
    }
    common.write_artifact(session.id, "egress_generate_guide", egress_snapshot)
    # Store summary (no payload) in DB so the frontend can read it.
    egress_db_summary = {k: v for k, v in egress_snapshot.items() if k != "payload"}
    egress_db_summary["path"] = common.artifact_storage_key(session.id, "egress_generate_guide")
    await common.record_stage(db, session, stage="egress_generate_guide", summary=egress_db_summary)
    # ---------------------------------------------------------------------

    result = await provider.generate_json(prompt=prompt)

    common.write_artifact(
        session.id,
        "generate_guide",
        {"prompt_chars": len(prompt), "raw_text": result.text, "raw": result.raw},
    )
    summary = {
        "path": common.artifact_storage_key(session.id, "generate_guide"),
        "output_chars": len(result.text),
    }
    await common.record_stage(db, session, stage="generate_guide", summary=summary)
    await common.add_ai_call(
        db,
        session,
        stage="generate_guide",
        model=result.model,
        input_chars=result.input_chars,
        output_chars=result.output_chars,
    )
