"""Stage: transcribe — OpenAI Whisper fallback path.

Used only when ``STT_PROVIDER=openai``. The default configuration uses
``transcribe_local`` (local-ai faster-whisper) instead; this stage is
retained so the pipeline can fall back to the OpenAI Whisper API by
changing a single env-var without code changes.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.config import settings
from app.models.session import Session
from app.pipeline import common
from app.storage.local import get_storage

log = logging.getLogger(__name__)


async def run(db: AsyncSession, session: Session, provider: AIProvider) -> None:
    if common.stage_done(session, "transcribe"):
        return

    audio_summary = (session.pipeline_artifacts or {}).get("extract_audio") or {}
    audio_key = audio_summary.get("audio_key")
    if not audio_key:
        raise RuntimeError("transcribe requires extract_audio to have run")

    # Prefer the compressed M4A when available — extract_audio produces it
    # when STT_PROVIDER=openai and the WAV would exceed the 25 MB API limit.
    audio_openai_key = audio_summary.get("audio_openai_key")
    if audio_openai_key:
        audio_path = get_storage().local_path(audio_openai_key)
        log.info("transcribe: using compressed audio (%s)", audio_openai_key)
    else:
        audio_path = get_storage().local_path(audio_key)
    language = settings.transcribe_language or None

    result = await provider.transcribe(audio_path, language=language)

    full_payload = {
        "text": result.text,
        "language": result.language,
        "segments": [asdict(s) for s in result.segments],
        "raw": result.raw,
    }
    common.write_artifact(session.id, "transcribe", full_payload)
    summary = {
        "path": common.artifact_storage_key(session.id, "transcribe"),
        "segment_count": len(result.segments),
        "language": result.language,
    }
    await common.record_stage(db, session, stage="transcribe", summary=summary)
    await common.add_ai_call(
        db,
        session,
        stage="transcribe",
        model=result.model,
        input_chars=0,
        output_chars=len(result.text or ""),
        audio_duration_sec=result.audio_duration_sec,
    )
