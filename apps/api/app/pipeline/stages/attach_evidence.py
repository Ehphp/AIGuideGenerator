"""Stage: attach_evidence (Phase F).

Runs immediately after ``validate_guide``. Reads the validated
``session.guide_content``, applies the deterministic nearest-frame
evidence-attachment algorithm, and writes the enriched content back to
``session.guide_content`` in the same DB transaction.

No LLM calls, no image loading — pure timestamp arithmetic over the
``extract_frames`` artifact that was already produced earlier in the pipeline.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.pipeline.evidence import attach_missing_click_evidence, guide_has_opacified_keys
from app.schemas.guide import Guide

log = logging.getLogger(__name__)


def _needs_rerun(session: Session) -> bool:
    """Return True if attach_evidence should re-run despite being marked done.

    This handles sessions whose guide_content still contains opacified frame_keys
    (stems like ``"frame_0002"`` produced by ``prepare_for_egress``) because
    they were processed before the stem-resolution fix was in place.
    """
    if not session.guide_content:
        return False
    frames: list[dict] = (session.pipeline_artifacts or {}).get("extract_frames") or []
    available_keys: set[str] = {str(f["key"]) for f in frames if isinstance(f.get("key"), str)}
    guide = Guide.model_validate(session.guide_content)
    return guide_has_opacified_keys(guide, available_keys)


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "attach_evidence") and not _needs_rerun(session):
        return

    if not session.guide_content:
        raise RuntimeError(
            "attach_evidence requires guide_content to be set by validate_guide"
        )

    frames: list[dict] = (session.pipeline_artifacts or {}).get("extract_frames") or []
    if not isinstance(frames, list):
        frames = []

    guide = Guide.model_validate(session.guide_content)
    guide = attach_missing_click_evidence(
        guide,
        frames,
        max_nearest_sec=settings.evidence_max_nearest_sec,
    )

    session.guide_content = guide.model_dump()
    await db.flush()

    # Count outcomes for observability (counters only — no raw text).
    from app.pipeline.evidence import step_has_click

    steps_with_click = sum(1 for s in guide.steps if step_has_click(s))
    attached_count = sum(
        1 for s in guide.steps if s.evidence.frame_source == "nearest_frame"
    )
    kept_llm = sum(
        1 for s in guide.steps if s.evidence.frame_source == "llm"
    )
    unresolved_count = sum(
        1 for s in guide.steps if s.evidence.frame_source == "none"
    )

    summary = {
        "step_count": len(guide.steps),
        "steps_with_click": steps_with_click,
        "attached_count": attached_count,
        "kept_llm": kept_llm,
        "unresolved_count": unresolved_count,
    }
    await common.record_stage(
        db,
        session,
        stage="attach_evidence",
        summary=summary,
        message=(
            f"attach_evidence: {attached_count} attached, "
            f"{kept_llm} kept (llm), {unresolved_count} unresolved"
        ),
    )
    log.info(
        "attach_evidence: steps=%d click=%d attached=%d kept_llm=%d unresolved=%d (session=%s)",
        len(guide.steps),
        steps_with_click,
        attached_count,
        kept_llm,
        unresolved_count,
        session.id,
    )
