"""Stage: generate_guide. LLM JSON-mode call producing a draft Guide JSON.

Prompt routing
--------------
If a ``content_classification`` artifact is present (written by the preceding
``classify_content`` stage), the prompt is chosen based on ``document_type``:

- ``procedural``   → ``procedural_generation.md``   (step-by-step guide)
- everything else  → ``adaptive_document_generation.md``  (sections-based)

If no classification artifact exists (e.g., the stage was skipped or this is
a re-run of an old session), the procedural prompt is used as a safe default.

Two-pass augmentation (Strategy B)
----------------------------------
If an ``extract_actions`` artifact is present (mined by the preceding stage),
its action list is appended to the prompt as structured evidence. The model
must consume those actions when building steps so that mined items are not
silently dropped.

Coverage retry (Strategy A)
---------------------------
After the first call, the produced guide is validated against the recording
duration. If a procedural guide produces fewer steps than
``ceil(duration_sec / 90)`` (floor 4), the model is invoked a second time
with a corrective feedback prompt. At most one retry is attempted to bound
cost; the retry result is accepted only if it produces strictly more steps.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.config import settings
from app.models.session import Session
from app.pipeline import common, safety
from app.pipeline.timeline_compress import compress_for_guide, log_payload_stats

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(document_type: str) -> str:
    """Return the generation prompt appropriate for *document_type*."""
    if document_type == "procedural":
        fname = "procedural_generation.md"
    else:
        fname = "adaptive_document_generation.md"
    path = _PROMPTS_DIR / fname
    return path.read_text()


def _get_document_type(session_id) -> str:
    """Read document_type from the content_classification artifact.

    Returns ``"procedural"`` as a safe default when the artifact is absent,
    malformed, or contains an unrecognised value.
    """
    classification = common.read_artifact(session_id, "content_classification")
    if not classification or not isinstance(classification, dict):
        log.debug(
            "generate_guide: no content_classification artifact — defaulting to procedural"
        )
        return "procedural"
    doc_type = str(classification.get("document_type", "")).lower().strip()
    valid = {"procedural", "technical", "conceptual", "diagnostic", "demo", "mixed"}
    if doc_type not in valid:
        log.warning(
            "generate_guide: unrecognised document_type %r in classification — defaulting to procedural",
            doc_type,
        )
        return "procedural"
    return doc_type


def _timeline_duration(timeline: dict) -> float:
    """Best-effort duration in seconds from a timeline artifact."""
    events = timeline.get("events") or []
    if not events:
        return 0.0
    last = 0.0
    for ev in events:
        for key in ("t_end", "t"):
            v = ev.get(key)
            if isinstance(v, (int, float)) and v > last:
                last = float(v)
    return last


def _coverage_targets(duration_sec: float) -> int:
    """Minimum step count for a procedural guide given recording duration."""
    if duration_sec <= 0:
        return 4
    return max(4, math.ceil(duration_sec / 90.0))


def _parse_guide(text: str) -> dict | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _step_count(guide: dict | None) -> int:
    if not guide:
        return 0
    steps = guide.get("steps")
    return len(steps) if isinstance(steps, list) else 0


def _retry_feedback_prompt(
    *,
    prior_text: str,
    produced_steps: int,
    target_min_steps: int,
    duration_sec: float,
    action_count: int,
) -> str:
    """Build a feedback prompt for the coverage retry call."""
    duration_min = duration_sec / 60.0
    return (
        "Your previous attempt produced an incomplete guide and is REJECTED.\n\n"
        f"You produced {produced_steps} step(s) for a recording that is "
        f"{duration_min:.1f} minute(s) long. The target for this duration "
        f"is at least {target_min_steps} steps "
        "(roughly one step per 60–120 seconds of substantive activity).\n\n"
        "You ALREADY received the timeline and "
        f"{action_count} pre-mined atomic actions in the previous turn. "
        "Use them. Each high-confidence mined action that is not already covered "
        "by an existing step MUST become its own step.\n\n"
        "Forbidden patterns in your previous output:\n"
        "- meta-steps such as 'Setup environment' or 'Run application'\n"
        "- compound descriptions combining multiple verb-target pairs\n"
        "- generic prerequisites/warnings not anchored to a timeline event\n"
        "- merging an OPEN and a RUN/CLICK into a single step\n\n"
        "Produce a NEW guide following exactly the same JSON schema as before "
        f"but with at least {target_min_steps} steps. Do NOT remove the "
        "concrete steps you had — split them further. Return ONLY the JSON "
        "object, no commentary.\n\n"
        "Your previous (rejected) output, for reference:\n"
        "```json\n" + prior_text[:8000] + "\n```\n"
    )


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
    duration_sec = _timeline_duration(timeline_egress)

    # Compress before sending to reduce token count.
    timeline_compressed, compress_stats = compress_for_guide(timeline_egress, settings=settings)
    log_payload_stats("generate_guide", timeline_egress, timeline_compressed, compress_stats)

    # Strategy B (two-pass): read the mined action list, if any. The action
    # list was produced from the same sanitized timeline, so it is already
    # safe for egress; we still run prepare_for_egress for belt-and-braces.
    action_list = common.read_artifact(session.id, "extract_actions")
    if action_list and isinstance(action_list, dict):
        action_list_egress = safety.prepare_for_egress(
            action_list, context="generate_guide_actions"
        )
    else:
        action_list_egress = None
    actions_arr = (action_list_egress or {}).get("actions") or []

    # Select the generation prompt based on content classification.
    document_type = _get_document_type(session.id)
    base_prompt = _load_prompt(document_type)

    prompt_parts = [
        base_prompt,
        "\n```json\n",
        json.dumps(timeline_compressed, ensure_ascii=False),
        "\n```\n",
    ]
    if action_list_egress and actions_arr:
        prompt_parts.append(
            "\nACTION_LIST (pre-mined atomic actions from the timeline — "
            "USE these as a recall floor; each entry with confidence >= 0.5 "
            "should appear in at least one step):\n```json\n"
        )
        prompt_parts.append(json.dumps(action_list_egress, ensure_ascii=False))
        prompt_parts.append("\n```\n")
    prompt = "".join(prompt_parts)

    # --- Egress audit artifact -------------------------------------------
    # Exact snapshot of what was sent to the external LLM, saved locally for
    # operator inspection. Never served to the UI in raw form; public_artifacts
    # exposes only a summary (prompt_chars, event counts, flags).
    events = timeline_egress.get("events") or []
    target_min_steps = (
        _coverage_targets(duration_sec) if document_type == "procedural" else 0
    )
    egress_snapshot: dict = {
        "prompt_chars": len(prompt),
        "timeline_language": timeline_egress.get("language"),
        "events_total": len(events),
        "transcript_events": sum(1 for e in events if e.get("kind") == "transcript"),
        "frame_events": sum(1 for e in events if e.get("kind") == "frame"),
        "sanitize_enabled": settings.sanitize_enabled,
        "ocr_provider": settings.ocr_provider,
        "frame_keys_opacified": True,
        "document_type": document_type,
        "actions_count": len(actions_arr),
        "duration_sec": round(duration_sec, 2),
        "target_min_steps": target_min_steps,
        "payload": timeline_egress,
    }
    common.write_artifact(session.id, "egress_generate_guide", egress_snapshot)
    # Store summary (no payload) in DB so the frontend can read it.
    egress_db_summary = {k: v for k, v in egress_snapshot.items() if k != "payload"}
    egress_db_summary["path"] = common.artifact_storage_key(session.id, "egress_generate_guide")
    await common.record_stage(db, session, stage="egress_generate_guide", summary=egress_db_summary)
    # ---------------------------------------------------------------------

    result = await provider.generate_json(
        prompt=prompt,
        max_completion_tokens=settings.openai_generate_guide_max_completion_tokens,
    )
    total_input_chars = result.input_chars
    total_output_chars = result.output_chars
    final_text = result.text
    final_model = result.model

    # --- Strategy A: coverage validator + single retry on undershoot -----
    coverage_meta: dict = {
        "document_type": document_type,
        "duration_sec": round(duration_sec, 2),
        "target_min_steps": target_min_steps,
        "attempts": 1,
        "first_pass_steps": _step_count(_parse_guide(result.text)),
        "retried": False,
        "final_steps": 0,
    }

    if document_type == "procedural" and target_min_steps > 0:
        first_guide = _parse_guide(result.text)
        first_steps = _step_count(first_guide)
        if first_steps < target_min_steps:
            log.warning(
                "generate_guide: coverage undershoot (%d < %d) for %.1fs — retrying",
                first_steps,
                target_min_steps,
                duration_sec,
            )
            feedback = _retry_feedback_prompt(
                prior_text=result.text,
                produced_steps=first_steps,
                target_min_steps=target_min_steps,
                duration_sec=duration_sec,
                action_count=len(actions_arr),
            )
            try:
                retry_result = await provider.generate_json(
                    prompt=feedback,
                    max_completion_tokens=settings.openai_generate_guide_max_completion_tokens,
                )
                retry_guide = _parse_guide(retry_result.text)
                retry_steps = _step_count(retry_guide)
                coverage_meta["attempts"] = 2
                coverage_meta["retried"] = True
                coverage_meta["retry_steps"] = retry_steps
                # Accept the retry only if it is strictly better.
                if retry_steps > first_steps:
                    final_text = retry_result.text
                    final_model = retry_result.model
                    total_input_chars += retry_result.input_chars
                    total_output_chars += retry_result.output_chars
                    log.info(
                        "generate_guide: retry accepted (%d -> %d steps)",
                        first_steps,
                        retry_steps,
                    )
                else:
                    log.warning(
                        "generate_guide: retry rejected (%d -> %d steps); keeping first attempt",
                        first_steps,
                        retry_steps,
                    )
                await common.add_ai_call(
                    db,
                    session,
                    stage="generate_guide_retry",
                    model=retry_result.model,
                    input_chars=retry_result.input_chars,
                    output_chars=retry_result.output_chars,
                )
            except Exception as exc:  # noqa: BLE001 — never block pipeline on retry
                log.warning(
                    "generate_guide: retry call failed (%s) — keeping first attempt",
                    exc,
                )
                coverage_meta["retry_error"] = str(exc)[:200]

    coverage_meta["final_steps"] = _step_count(_parse_guide(final_text))
    # ---------------------------------------------------------------------

    common.write_artifact(
        session.id,
        "generate_guide",
        {
            "prompt_chars": len(prompt),
            "raw_text": final_text,
            "raw": result.raw,
            "coverage": coverage_meta,
        },
    )
    summary = {
        "path": common.artifact_storage_key(session.id, "generate_guide"),
        "output_chars": len(final_text),
        "document_type": document_type,
        "coverage": coverage_meta,
    }
    await common.record_stage(db, session, stage="generate_guide", summary=summary)
    await common.add_ai_call(
        db,
        session,
        stage="generate_guide",
        model=final_model,
        input_chars=total_input_chars,
        output_chars=total_output_chars,
    )
