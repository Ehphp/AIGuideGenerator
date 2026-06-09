"""Pipeline orchestrator: runs the stages of the AI pipeline in order.

Stages are idempotent: each stage early-exits if its summary is already
present in `session.pipeline_artifacts`. This makes `/retry` work cleanly
by simply re-running the orchestrator after a transition back to processing.

Each stage runs in its own committed transaction so that `progress_message`
is visible to external readers (the API polling endpoint) as soon as the
stage starts, without waiting for the entire pipeline to commit.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import update

from app.ai import get_ai_provider
from app.config import settings
from app.db import SessionLocal
from app.models.session import Session
from app.pipeline.stages import (
    analyze_frames,
    attach_evidence,
    build_timeline,
    classify_content,
    extract_actions,
    extract_audio,
    extract_frames,
    extract_visual_facts,
    generate_guide,
    grounding_validator,
    ingest,
    ocr_frames_local,
    parse_screens,
    rehydrate_guide,
    sanitize_timeline,
    transcribe,
    transcribe_local,
    validate_guide,
)
from app.services import session_service

log = logging.getLogger(__name__)


async def run(session_id: uuid.UUID) -> None:
    """Run all pipeline stages for the given session.

    Each stage is an independent committed transaction so that progress is
    visible to the API in real time.  The caller is responsible for
    transitioning the session to ``processing`` before calling this function.
    """
    provider = get_ai_provider()

    async def _stage(progress: str, stage_fn, *extra_args) -> None:
        """Commit a progress message, then run *stage_fn* in its own transaction."""
        # Commit progress so pollers see it immediately.
        async with SessionLocal() as db:
            async with db.begin():
                await db.execute(
                    update(Session)
                    .where(Session.id == session_id)
                    .values(progress_message=progress)
                )
        # Run the stage with a fresh session in its own transaction.
        async with SessionLocal() as db:
            async with db.begin():
                session = await session_service.get_session(db, session_id)
                await stage_fn(db, session, *extra_args)

    log.info("pipeline: ingest")
    await _stage("Probing media", ingest.run)

    log.info("pipeline: extract_audio")
    await _stage("Extracting audio", extract_audio.run)

    if settings.stt_provider.lower() == "local":
        log.info("pipeline: transcribe (local)")
        await _stage("Transcribing", transcribe_local.run)
    else:
        log.info("pipeline: transcribe (openai)")
        await _stage("Transcribing", transcribe.run, provider)

    log.info("pipeline: extract_frames")
    await _stage("Extracting frames", extract_frames.run)

    if settings.ocr_provider.lower() == "local":
        log.info("pipeline: analyze_frames (local-ocr)")
        await _stage("Analyzing frames", ocr_frames_local.run)
    else:
        log.info("pipeline: analyze_frames (openai-vision)")
        await _stage("Analyzing frames", analyze_frames.run, provider)

    log.info("pipeline: extract_visual_facts")
    await _stage("Extracting visual facts", extract_visual_facts.run)

    log.info("pipeline: parse_screens")
    await _stage("Parsing screens", parse_screens.run)

    log.info("pipeline: build_timeline")
    await _stage("Building timeline", build_timeline.run)

    if settings.sanitize_enabled:
        log.info("pipeline: sanitize_timeline")
        await _stage("Sanitizing timeline", sanitize_timeline.run)

    log.info("pipeline: classify_content")
    await _stage("Classifying content", classify_content.run, provider)

    log.info("pipeline: extract_actions")
    await _stage("Mining actions", extract_actions.run, provider)

    log.info("pipeline: generate_guide")
    await _stage("Generating guide", generate_guide.run, provider)

    if settings.sanitize_enabled:
        log.info("pipeline: rehydrate_guide")
        await _stage("Rehydrating guide", rehydrate_guide.run)

    log.info("pipeline: validate_guide")
    await _stage("Validating guide", validate_guide.run, provider)

    log.info("pipeline: grounding_validator")
    await _stage("Grounding validation", grounding_validator.run)

    log.info("pipeline: attach_evidence")
    await _stage("Attaching evidence", attach_evidence.run)

    async with SessionLocal() as db:
        async with db.begin():
            session = await session_service.get_session(db, session_id)
            await session_service.transition_status(
                db, session, "ready", progress_message="Guide ready"
            )
