"""Stage: extract_actions (two-pass generation, pass 1).

Mines a flat, exhaustive list of atomic actions from the sanitized timeline.
The result is consumed by ``generate_guide`` as additional structured evidence
to fight LLM over-summarisation on long procedural recordings.

The stage is safe to re-run: it is idempotent via ``stage_done``.
It does NOT replace ``generate_guide`` — it augments it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.config import settings
from app.models.session import Session
from app.pipeline import common, safety
from app.pipeline.timeline_compress import compress_for_guide, log_payload_stats

log = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "extract_actions.md"
)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _normalise(raw: dict) -> dict:
    """Defensive normalisation; never raise on bad LLM output."""
    actions_in = raw.get("actions")
    if not isinstance(actions_in, list):
        actions_in = []

    actions_out: list[dict] = []
    for i, a in enumerate(actions_in, start=1):
        if not isinstance(a, dict):
            continue
        try:
            t = float(a.get("t", 0.0))
        except (TypeError, ValueError):
            t = 0.0
        verb = str(a.get("verb") or "").upper().strip()[:24] or "CLICK"
        target = str(a.get("target") or "").strip()[:200]
        value = a.get("value")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)[:500]
        source = str(a.get("source") or "").lower().strip()
        if source not in {"transcript", "frame", "both"}:
            source = "transcript"
        excerpt = str(a.get("transcript_excerpt") or "")[:240]
        frame_keys = a.get("frame_keys") or []
        if not isinstance(frame_keys, list):
            frame_keys = []
        frame_keys = [str(k) for k in frame_keys if isinstance(k, str)][:6]
        try:
            conf = float(a.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))

        # Anti-hallucination guard: every action MUST have at least one
        # anchor — either a transcript_excerpt (audio source) or a
        # frame_keys entry (visual source). Actions with neither are LLM
        # inferences with no traceable evidence and are silently dropped.
        if not excerpt.strip() and not frame_keys:
            continue

        actions_out.append(
            {
                "id": f"act-{i}",
                "t": round(t, 2),
                "verb": verb,
                "target": target,
                "value": value,
                "source": source,
                "transcript_excerpt": excerpt,
                "frame_keys": frame_keys,
                "confidence": round(conf, 3),
            }
        )

    # Sort by t ascending; reassign ids after sort to keep them monotonic.
    actions_out.sort(key=lambda a: a["t"])
    for i, a in enumerate(actions_out, start=1):
        a["id"] = f"act-{i}"

    notes = raw.get("notes") or []
    warnings = raw.get("warnings") or []
    if not isinstance(notes, list):
        notes = []
    if not isinstance(warnings, list):
        warnings = []
    notes = [str(n)[:500] for n in notes[:20]]
    warnings = [str(w)[:500] for w in warnings[:20]]

    return {"actions": actions_out, "notes": notes, "warnings": warnings}


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "extract_actions"):
        return

    if settings.sanitize_enabled:
        timeline = safety.read_public_artifact_for_llm(
            session.id, "sanitize_timeline"
        )
        if not timeline:
            raise RuntimeError(
                "extract_actions (sanitize_enabled) requires sanitize_timeline"
            )
        safety.assert_not_raw_artifact(timeline, context="extract_actions")
    else:
        timeline = common.read_artifact(session.id, "build_timeline")
        if not timeline:
            raise RuntimeError(
                "extract_actions requires build_timeline to have run"
            )

    timeline_egress = safety.prepare_for_egress(
        timeline, context="extract_actions"
    )

    # Compress before sending to reduce token count (same preset as generate_guide:
    # keep all events but truncate OCR and drop empty frames).
    timeline_compressed, compress_stats = compress_for_guide(timeline_egress, settings=settings)
    log_payload_stats("extract_actions", timeline_egress, timeline_compressed, compress_stats)

    prompt = (
        _load_prompt()
        + "\n```json\n"
        + json.dumps(timeline_compressed, ensure_ascii=False)
        + "\n```\n"
    )

    # Egress audit (payload kept on disk, summary in DB).
    events = timeline_compressed.get("events") or []
    egress_snapshot: dict = {
        "prompt_chars": len(prompt),
        "events_total": len(events),
        "transcript_events": sum(1 for e in events if e.get("kind") == "transcript"),
        "frame_events": sum(1 for e in events if e.get("kind") == "frame"),
        "sanitize_enabled": settings.sanitize_enabled,
        "frame_keys_opacified": True,
        "payload_compressed": settings.llm_payload_compress,
        "payload": timeline_compressed,
    }
    common.write_artifact(session.id, "egress_extract_actions", egress_snapshot)
    egress_db_summary = {k: v for k, v in egress_snapshot.items() if k != "payload"}
    egress_db_summary["path"] = common.artifact_storage_key(
        session.id, "egress_extract_actions"
    )
    await common.record_stage(
        db, session, stage="egress_extract_actions", summary=egress_db_summary
    )

    result = await provider.generate_json(
        prompt=prompt,
        max_completion_tokens=settings.openai_extract_actions_max_completion_tokens,
    )

    try:
        raw = json.loads(result.text)
        if not isinstance(raw, dict):
            raise ValueError("LLM returned non-dict JSON")
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "extract_actions: LLM output is not valid JSON (%s) — storing empty list",
            exc,
        )
        raw = {}

    normalised = _normalise(raw)
    common.write_artifact(session.id, "extract_actions", normalised)

    summary = {
        "path": common.artifact_storage_key(session.id, "extract_actions"),
        "actions_count": len(normalised["actions"]),
        "output_chars": len(result.text),
    }
    await common.record_stage(
        db,
        session,
        stage="extract_actions",
        summary=summary,
        message=f"extract_actions: {len(normalised['actions'])} actions mined",
    )
    await common.add_ai_call(
        db,
        session,
        stage="extract_actions",
        model=result.model,
        input_chars=result.input_chars,
        output_chars=result.output_chars,
    )

    log.info(
        "extract_actions: %d actions (session=%s)",
        len(normalised["actions"]),
        session.id,
    )
