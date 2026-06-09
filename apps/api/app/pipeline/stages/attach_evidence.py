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
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.pipeline.evidence import attach_missing_click_evidence, guide_has_opacified_keys
from app.schemas.guide import Guide

log = logging.getLogger(__name__)

# Stop-words excluded from overlap check (same spirit as grounding_validator).
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into",
    "not", "new", "only", "all", "more", "button", "click", "open",
    "il", "la", "le", "di", "da", "in", "su", "un", "una", "del",
    "che", "con", "non", "per", "gli", "degli", "alla", "nel", "nella",
    "apri", "clicca", "premi", "sul", "sulla",
})


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z\u00c0-\u017f][A-Za-z\u00c0-\u017f0-9_-]{2,}", text or "")
        if t.lower() not in _STOPWORDS
    }


def _verify_overlap_and_drop_random(
    guide: Guide, visual_facts: list[dict]
) -> tuple[Guide, int]:
    """Drop nearest_frame attachments whose OCR has zero overlap with the step.

    Only applied when:
    - frame_source == "nearest_frame" (LLM-chosen frames are trusted)
    - the frame's OCR text is substantive (>= 20 chars)
    - the step has a meaningful title/target to compare against

    Returns (guide, drops_count).
    """
    if not visual_facts:
        return guide, 0
    by_key: dict[str, str] = {}
    for vf in visual_facts:
        key = vf.get("frame_key")
        if not isinstance(key, str):
            continue
        # Concatenate every meaningful text field for matching.
        parts: list[str] = []
        for el in vf.get("visible_ui_elements") or vf.get("elements") or []:
            if isinstance(el, dict) and el.get("text"):
                parts.append(str(el["text"]))
        for pa in vf.get("possible_actions") or []:
            if isinstance(pa, dict) and pa.get("target"):
                parts.append(str(pa["target"]))
        by_key[key] = " ".join(parts)

    drops = 0
    for step in guide.steps:
        if step.evidence.frame_source != "nearest_frame":
            continue
        keys = step.evidence.frame_keys or []
        if not keys:
            continue
        ocr_text = by_key.get(keys[0], "")
        if len(ocr_text) < 20:
            # Frame has too little OCR signal — keep attachment (no negative evidence).
            continue
        action_targets = " ".join(
            (a.target or "") for a in step.actions
        )
        step_text = f"{step.title or ''} {action_targets}"
        step_tokens = _tokens(step_text)
        if not step_tokens:
            continue
        ocr_tokens = _tokens(ocr_text)
        if step_tokens & ocr_tokens:
            continue
        # No overlap — the deterministic selector picked a frame that does
        # not visually support this step. Better to show no screenshot than
        # a misleading one.
        step.evidence.frame_keys = []
        step.evidence.frame_source = "none"
        step.evidence.frame_distance_sec = None
        drops += 1
    return guide, drops


def _needs_rerun(session: Session) -> bool:
    """Return True if attach_evidence should re-run despite being marked done.

    This handles sessions whose guide_content still contains opacified frame_keys
    (stems like ``"frame_0002"`` produced by ``prepare_for_egress``) because
    they were processed before the stem-resolution fix was in place.
    """
    if not session.guide_content:
        return False
    raw = (session.pipeline_artifacts or {}).get("extract_frames") or []
    frames: list[dict] = raw.get("frames", raw) if isinstance(raw, dict) else raw
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

    raw = (session.pipeline_artifacts or {}).get("extract_frames") or []
    frames: list[dict] = raw.get("frames", raw) if isinstance(raw, dict) else raw
    if not isinstance(frames, list):
        frames = []

    guide = Guide.model_validate(session.guide_content)
    guide = attach_missing_click_evidence(
        guide,
        frames,
        max_nearest_sec=settings.evidence_max_nearest_sec,
    )

    # Post-attachment overlap check: drop nearest_frame links whose OCR has
    # zero token overlap with the step's title/targets. Avoids "random"
    # screenshots being attached to steps they don't depict.
    visual_facts_artifact = common.read_artifact(session.id, "visual_facts")
    visual_facts: list[dict] = []
    if isinstance(visual_facts_artifact, dict):
        vf = visual_facts_artifact.get("frames") or visual_facts_artifact.get("visual_facts")
        if isinstance(vf, list):
            visual_facts = vf
    elif isinstance(visual_facts_artifact, list):
        visual_facts = visual_facts_artifact
    guide, low_overlap_drops = _verify_overlap_and_drop_random(guide, visual_facts)

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
        "low_overlap_drops": low_overlap_drops,
    }
    await common.record_stage(
        db,
        session,
        stage="attach_evidence",
        summary=summary,
        message=(
            f"attach_evidence: {attached_count} attached, "
            f"{kept_llm} kept (llm), {unresolved_count} unresolved, "
            f"{low_overlap_drops} dropped (low overlap)"
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
