"""Stage: analyze_frames — OpenAI Vision fallback path.

Used only when ``OCR_PROVIDER=openai``. The default configuration uses
``ocr_frames_local`` (local-ai Tesseract/PaddleOCR) instead; this stage
is retained so the pipeline can fall back to GPT-4o Vision by changing
a single env-var without code changes.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage

log = logging.getLogger(__name__)


def _load_prompt() -> str:
    p = Path(__file__).resolve().parent.parent / "prompts" / "frame_analysis.md"
    return p.read_text()


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "analyze_frames"):
        return

    raw = (session.pipeline_artifacts or {}).get("extract_frames") or []
    frames = raw.get("frames", raw) if isinstance(raw, dict) else raw
    if not isinstance(frames, list) or not frames:
        raise RuntimeError("analyze_frames requires extract_frames to have produced frames")

    prompt = _load_prompt()
    storage = get_storage()

    full_results: list[dict] = []
    summary: list[dict] = []
    total_input = 0
    total_output = 0
    model_name = ""

    # Sequential to keep cost predictable and avoid rate limits.
    for f in frames:
        idx = int(f["idx"])
        t = float(f["t"])
        key = str(f["key"])
        img_path = storage.local_path(key)
        analysis = await provider.analyze_frame(img_path, prompt=prompt)
        model_name = analysis.model or model_name
        total_input += analysis.input_chars
        total_output += analysis.output_chars
        full_results.append(
            {
                "idx": idx,
                "t": t,
                "key": key,
                "ocr_text": analysis.ocr_text,
                "ui_summary": analysis.ui_summary,
                "raw": analysis.raw,
            }
        )
        summary.append(
            {
                "idx": idx,
                "t": t,
                "key": key,
                "ocr_text": analysis.ocr_text,
                "ui_summary": analysis.ui_summary,
            }
        )

    common.write_artifact(session.id, "analyze_frames", full_results)
    await common.record_stage(
        db,
        session,
        stage="analyze_frames",
        summary=summary,
        message=f"analyzed {len(summary)} frames",
    )
    await common.add_ai_call(
        db,
        session,
        stage="analyze_frames",
        model=model_name or "vision",
        input_chars=total_input,
        output_chars=total_output,
        frame_count=len(summary),
    )
