"""Stage: classify_content.

Lightweight LLM call that reads the current timeline and infers what kind of
documentation would best describe the recorded content.

Produces the ``content_classification`` artifact used by ``generate_guide``
to select the appropriate generation prompt and output shape.

The stage is intentionally cheap: it uses a short focused prompt with a
small JSON output (< 200 tokens) so the cost is negligible.
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
from app.pipeline.timeline_compress import compress_for_classify, log_payload_stats

log = logging.getLogger(__name__)

# Valid enum values — used for defensive normalisation.
_VALID_DOCUMENT_TYPES = frozenset(
    {"procedural", "technical", "conceptual", "diagnostic", "demo", "mixed"}
)
_VALID_AUDIENCES = frozenset(
    {"end_user", "developer", "sysadmin", "operator", "mixed"}
)
_VALID_OUTPUT_SHAPES = frozenset({"steps", "sections", "hybrid"})


def _load_prompt() -> str:
    p = (
        Path(__file__).resolve().parent.parent
        / "prompts"
        / "classify_content.md"
    )
    return p.read_text()


def _normalise(raw: dict) -> dict:
    """Defensively normalise the LLM output; fill defaults for missing/bad fields."""
    doc_type = str(raw.get("document_type", "")).lower().strip()
    if doc_type not in _VALID_DOCUMENT_TYPES:
        log.warning(
            "classify_content: unrecognised document_type %r — defaulting to 'procedural'",
            doc_type,
        )
        doc_type = "procedural"

    audience = str(raw.get("intended_audience", "")).lower().strip()
    if audience not in _VALID_AUDIENCES:
        audience = "mixed"

    output_shape = str(raw.get("recommended_output_shape", "")).lower().strip()
    if output_shape not in _VALID_OUTPUT_SHAPES:
        # Derive from document_type as fallback.
        output_shape = "steps" if doc_type == "procedural" else "sections"

    try:
        confidence = float(raw.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    primary_signals = raw.get("primary_signals") or []
    if not isinstance(primary_signals, list):
        primary_signals = []
    primary_signals = [str(s)[:120] for s in primary_signals[:6]]

    recommended_sections = raw.get("recommended_sections") or []
    if not isinstance(recommended_sections, list):
        recommended_sections = []
    recommended_sections = [str(s)[:120] for s in recommended_sections[:8]]

    rationale = str(raw.get("rationale") or "")[:500]

    return {
        "document_type": doc_type,
        "confidence": round(confidence, 3),
        "intended_audience": audience,
        "recommended_output_shape": output_shape,
        "primary_signals": primary_signals,
        "recommended_sections": recommended_sections,
        "rationale": rationale,
    }


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "classify_content"):
        return

    # Read the same timeline that generate_guide will use.
    if settings.sanitize_enabled:
        timeline = safety.read_public_artifact_for_llm(
            session.id, "sanitize_timeline"
        )
        if not timeline:
            raise RuntimeError(
                "classify_content (sanitize_enabled) requires sanitize_timeline"
            )
        safety.assert_not_raw_artifact(timeline, context="classify_content")
    else:
        timeline = common.read_artifact(session.id, "build_timeline")
        if not timeline:
            raise RuntimeError(
                "classify_content requires build_timeline to have run"
            )

    timeline_egress = safety.prepare_for_egress(timeline, context="classify_content")

    # Compress before sending: classify_content only needs a representative
    # sample; stripping raw OCR and capping frame events keeps this call well
    # under the Tier-1 TPM limit.
    timeline_compressed, compress_stats = compress_for_classify(timeline_egress, settings=settings)
    log_payload_stats("classify_content", timeline_egress, timeline_compressed, compress_stats)

    prompt = (
        _load_prompt()
        + "\n```json\n"
        + json.dumps(timeline_compressed, ensure_ascii=False)
        + "\n```\n"
    )

    result = await provider.generate_json(
        prompt=prompt,
        max_completion_tokens=settings.openai_classify_max_completion_tokens,
    )

    # Parse and normalise.
    try:
        raw = json.loads(result.text)
        if not isinstance(raw, dict):
            raise ValueError("LLM returned non-dict JSON")
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "classify_content: LLM output is not valid JSON (%s) — defaulting to procedural",
            exc,
        )
        raw = {}

    classification = _normalise(raw)

    common.write_artifact(session.id, "content_classification", classification)

    summary: dict = {
        "path": common.artifact_storage_key(session.id, "content_classification"),
        "document_type": classification["document_type"],
        "confidence": classification["confidence"],
        "intended_audience": classification["intended_audience"],
        "recommended_output_shape": classification["recommended_output_shape"],
    }
    await common.record_stage(
        db,
        session,
        stage="classify_content",
        summary=summary,
        message=(
            f"classify_content: {classification['document_type']} "
            f"(conf={classification['confidence']:.2f}, "
            f"audience={classification['intended_audience']}, "
            f"shape={classification['recommended_output_shape']})"
        ),
    )
    await common.add_ai_call(
        db,
        session,
        stage="classify_content",
        model=result.model,
        input_chars=result.input_chars,
        output_chars=result.output_chars,
    )

    log.info(
        "classify_content: document_type=%s confidence=%.2f audience=%s (session=%s)",
        classification["document_type"],
        classification["confidence"],
        classification["intended_audience"],
        session.id,
    )
