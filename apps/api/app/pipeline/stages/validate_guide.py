"""Stage: validate_guide.

Validates the LLM JSON output against the Pydantic Guide schema. If validation
fails, makes one repair pass by re-prompting the LLM with the validation errors.
On success, persists `guide_content` (JSONB) on the session.

Phase E: when `settings.sanitize_enabled` is on, the input is the
**rehydrated** guide produced by `rehydrate_guide`. Any repair pass MUST
re-prompt with the **placeholder** text (not the rehydrated one) to keep
sanitized data inside the LLM boundary; the repaired output is then
re-rehydrated before final parsing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.config import settings
from app.models.session import Session
from app.pipeline import common, safety
from app.pipeline.normalize_actions import normalize_guide_dict
from app.pipeline.stages.rehydrate_guide import _load_redaction_map
from app.sanitize import rehydrate_text
from app.schemas.guide import GUIDE_SCHEMA_VERSION, Guide

log = logging.getLogger(__name__)


def _try_parse(raw_text: str) -> tuple[Guide | None, str | None]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if isinstance(data, dict):
        data = normalize_guide_dict(data)
    try:
        return Guide.model_validate(data), None
    except ValidationError as e:
        return None, e.json()


def _build_repair_prompt(err: str | None, raw_text: str) -> str:
    return (
        "Your previous output failed schema validation. Errors:\n"
        f"{err}\n\n"
        "Return ONLY a corrected JSON object that matches the Guide v1.1 schema.\n"
        "The key change from v1.0: `steps` is now optional (default []); "
        "`sections`, `document_type`, and `intended_audience` are new optional fields.\n\n"
        "Previous output:\n```json\n" + raw_text + "\n```\n"
    )


async def _repair_loop_legacy(
    db: AsyncSession,
    session: Session,
    provider: AIProvider,
    raw_text: str,
    err: str | None,
    max_completion_tokens: int | None = None,
) -> Guide:
    repair_prompt = _build_repair_prompt(err, raw_text)
    _egress_repair = {
        "kind": "legacy",
        "prompt_chars": len(repair_prompt),
        "sanitize_enabled": settings.sanitize_enabled,
        "first_error_len": len(err) if err else 0,
    }
    common.write_artifact(session.id, "egress_validate_repair", _egress_repair)
    await common.record_stage(db, session, stage="egress_validate_repair", summary=_egress_repair)
    result = await provider.generate_json(
        prompt=repair_prompt,
        max_completion_tokens=max_completion_tokens,
    )
    common.write_artifact(
        session.id,
        "validate_guide",
        {"first_error": err, "repaired_text": result.text, "raw": result.raw},
    )
    await common.add_ai_call(
        db,
        session,
        stage="validate_guide",
        model=result.model,
        input_chars=result.input_chars,
        output_chars=result.output_chars,
    )
    guide, err2 = _try_parse(result.text)
    if guide is None:
        raise RuntimeError(f"guide schema validation failed after repair: {err2}")
    return guide


async def _repair_loop_sanitized(
    db: AsyncSession,
    session: Session,
    provider: AIProvider,
    placeholder_text: str,
    err: str | None,
    max_completion_tokens: int | None = None,
) -> Guide:
    """Repair pass for the sanitize-enabled path.

    The repair prompt is built from the **placeholder** text only — never
    the rehydrated text — so no raw values cross the LLM boundary. The
    repaired output is rehydrated locally before parsing.
    """
    repair_prompt = _build_repair_prompt(err, placeholder_text)
    safety.assert_not_raw_artifact(repair_prompt, context="validate_guide.repair")
    _egress_repair = {
        "kind": "sanitized",
        "prompt_chars": len(repair_prompt),
        "sanitize_enabled": settings.sanitize_enabled,
        "first_error_len": len(err) if err else 0,
    }
    common.write_artifact(session.id, "egress_validate_repair", _egress_repair)
    await common.record_stage(db, session, stage="egress_validate_repair", summary=_egress_repair)
    result = await provider.generate_json(
        prompt=repair_prompt,
        max_completion_tokens=max_completion_tokens,
    )

    redaction_map = _load_redaction_map(session.id)
    rehydrated, stats = rehydrate_text(result.text, redaction_map)

    common.write_artifact(
        session.id,
        "validate_guide",
        {
            "first_error": err,
            "repaired_placeholder_text": result.text,
            "repaired_text": rehydrated,
            "placeholders_resolved": stats.resolved,
            "placeholders_unresolved": stats.unresolved,
            "raw": result.raw,
        },
    )
    await common.add_ai_call(
        db,
        session,
        stage="validate_guide",
        model=result.model,
        input_chars=result.input_chars,
        output_chars=result.output_chars,
    )
    guide, err2 = _try_parse(rehydrated)
    if guide is None:
        raise RuntimeError(f"guide schema validation failed after repair: {err2}")
    return guide


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "validate_guide") and session.guide_content:
        return

    rehydrate_artifact = (
        common.read_artifact(session.id, "rehydrate_guide")
        if settings.sanitize_enabled
        else None
    )

    if rehydrate_artifact and "raw_text" in rehydrate_artifact:
        raw_text = rehydrate_artifact["raw_text"]
        placeholder_text = rehydrate_artifact.get("placeholder_text", "")
        guide, err = _try_parse(raw_text)
        if guide is None:
            log.warning(
                "guide validation failed (sanitized path); attempting one repair pass: %s",
                err,
            )
            guide = await _repair_loop_sanitized(
                db, session, provider, placeholder_text, err,
                max_completion_tokens=settings.openai_validate_guide_max_completion_tokens,
            )
        else:
            common.write_artifact(
                session.id, "validate_guide", {"first_error": None, "ok": True}
            )
    else:
        gen = common.read_artifact(session.id, "generate_guide")
        if not gen or "raw_text" not in gen:
            raise RuntimeError("validate_guide requires generate_guide to have run")
        raw_text = gen["raw_text"]
        guide, err = _try_parse(raw_text)
        if guide is None:
            log.warning("guide validation failed; attempting one repair pass: %s", err)
            guide = await _repair_loop_legacy(
                db, session, provider, raw_text, err,
                max_completion_tokens=settings.openai_validate_guide_max_completion_tokens,
            )
        else:
            common.write_artifact(
                session.id, "validate_guide", {"first_error": None, "ok": True}
            )

    # Backfill metadata.
    md = guide.metadata
    md.generated_at = md.generated_at or datetime.now(timezone.utc).isoformat()
    md.source_session_id = md.source_session_id or str(session.id)
    if md.source_duration_sec is None and session.media_duration_sec:
        md.source_duration_sec = session.media_duration_sec

    session.guide_content = guide.model_dump()
    session.guide_schema_version = GUIDE_SCHEMA_VERSION
    session.guide_edited_at = None
    await db.flush()

    summary = {
        "path": common.artifact_storage_key(session.id, "validate_guide"),
        "step_count": len(guide.steps),
        "section_count": len(guide.sections),
        "document_type": guide.document_type or "procedural",
    }
    await common.record_stage(db, session, stage="validate_guide", summary=summary)
