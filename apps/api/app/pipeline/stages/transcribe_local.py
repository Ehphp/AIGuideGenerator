"""Stage: transcribe_local.  Local STT via the internal local-ai service.

Phase C.  This stage is a drop-in replacement for `transcribe` (OpenAI
Whisper-API) for sessions where `settings.stt_provider == "local"`.

Privacy contract:
- Only the storage **key** (`sessions/<uuid>/audio.wav`) is sent over the
  HTTP call to local-ai.  No audio bytes leave the host.
- The local-ai service resolves the key against the read-only
  `/data/storage` mount and never echoes the resolved path back.
- The full transcript text is stored in the artifact file as `"transcribe"`
  (same key as the OpenAI path) so downstream stages are transparent to
  which engine ran.  The raw transcript is NOT included in the
  `pipeline_artifacts` summary column (only metadata: segment count,
  language, artifact path).

Artifact written:
    sessions/<id>/artifacts/transcribe.json
    {
        "text": "...",
        "language": "it",
        "segments": [{"start": 0.0, "end": 2.5, "text": "..."}],
        "engine": "faster_whisper",
        "model": "small"
    }

Stage summary stored in pipeline_artifacts["transcribe"]:
    {
        "path": "sessions/<id>/artifacts/transcribe.json",
        "segment_count": N,
        "language": "it"
    }

This matches the shape produced by the OpenAI `transcribe` stage so
`build_timeline`, `generate_guide`, and all other downstream stages are
unaffected.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.local_client import LocalAIClient, LocalAIError
from app.config import settings
from app.models.session import Session
from app.pipeline import common

log = logging.getLogger(__name__)


async def run(db: AsyncSession, session: Session) -> None:
    """Run the local-STT stage, writing the same artifacts as `transcribe`."""
    # Idempotent: if the legacy or local transcribe stage already completed,
    # both write to the same artifact key ("transcribe"). Skip if done.
    if common.stage_done(session, "transcribe"):
        return

    audio_summary = (session.pipeline_artifacts or {}).get("extract_audio") or {}
    audio_key: str | None = audio_summary.get("audio_key")
    if not audio_key:
        raise RuntimeError("transcribe_local requires extract_audio to have run")

    language = settings.transcribe_language or None

    try:
        async with LocalAIClient(base_url=settings.local_ai_base_url) as client:
            response = await client.transcribe(audio_key=audio_key, language=language)
    except LocalAIError as exc:
        raise RuntimeError(f"local-ai transcribe failed: {exc!s}") from exc

    full_payload = {
        "text": response.text,
        "language": response.language,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in response.segments
        ],
        "engine": response.engine,
        "model": response.model,
    }
    common.write_artifact(session.id, "transcribe", full_payload)

    summary = {
        "path": common.artifact_storage_key(session.id, "transcribe"),
        "segment_count": len(response.segments),
        "language": response.language,
    }
    # Record under "transcribe" so all downstream stage checks are transparent.
    await common.record_stage(db, session, stage="transcribe", summary=summary)
    await common.add_ai_call(
        db,
        session,
        stage="transcribe",
        model=response.model,
        input_chars=0,
        output_chars=len(response.text or ""),
        audio_duration_sec=None,  # local engine does not report this yet
    )
