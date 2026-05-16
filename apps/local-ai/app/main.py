"""local-ai FastAPI entrypoint.

Phase B skeleton + Phase C local STT via faster-whisper.
Phase D (local OCR) will extend this file with the real OCR dispatch.
The contract — request/response schemas, key validation, error categories—
is locked here so the api-side client can remain stable.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.schemas import (
    ErrorResponse,
    HealthResponse,
    OCRFrameResult,
    OCRRequest,
    OCRResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from app.storage_resolver import (
    StorageKeyError,
    StorageNotFoundError,
    resolve_storage_key,
)

# Avoid INFO-level path logging by default; the resolver enforces this too,
# but keep the service quiet on the happy path.
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("local-ai")


app = FastAPI(title="local-ai", version="0.1.0")


# ---------------------------------------------------------------------------
# Error helpers
#
# We never echo the offending key back to the caller — only a category and
# a generic message. The caller already knows the key it sent.
# ---------------------------------------------------------------------------


def _raise_invalid_key() -> None:
    raise HTTPException(
        status_code=400,
        detail=ErrorResponse(
            category="invalid_key",
            message="storage key failed validation",
        ).model_dump(),
    )


def _raise_not_found() -> None:
    raise HTTPException(
        status_code=404,
        detail=ErrorResponse(
            category="not_found",
            message="storage key did not resolve to an existing file",
        ).model_dump(),
    )


def _check_key_and_resolve(key: str) -> Path:
    """Validate + resolve a storage key; maps resolver errors to HTTP responses.

    Returns the resolved :class:`pathlib.Path` on success.
    """
    try:
        return resolve_storage_key(key)
    except StorageKeyError:
        _raise_invalid_key()
    except StorageNotFoundError:
        _raise_not_found()


def _check_key(key: str) -> None:
    """Validate + resolve a key, discarding the resolved path."""
    _check_key_and_resolve(key)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True)


@app.post("/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    resolved = _check_key_and_resolve(req.audio_key)

    if settings.stt_engine == "faster_whisper":
        from app import stt_engine  # lazy: only import when engine is active

        result = stt_engine.transcribe(resolved)
        return TranscribeResponse(**result)

    # Stub mode (default). Phase B / test-friendly: no model required.
    return TranscribeResponse(
        text="",
        language=req.language,
        segments=[],
        engine="stub",
        model="stub",
    )


@app.post("/ocr", response_model=OCRResponse)
def ocr(req: OCRRequest) -> OCRResponse:
    # Safety cap so a single batch can't pin the worker.
    if len(req.frame_keys) > settings.ocr_max_frames_per_request:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                category="invalid_key",
                message="too many frame_keys in a single request",
            ).model_dump(),
        )

    # Validate every key BEFORE returning anything. A single bad key fails
    # the whole batch — intentional (prevents partial results masking injection).
    resolved_paths: list[Path] = [_check_key_and_resolve(key) for key in req.frame_keys]

    # Stub mode (default) — keep tests fast / no native OCR required.
    if settings.ocr_engine == "stub":
        results = [
            OCRFrameResult(
                frame_key=key,
                engine="stub",
                model="stub",
                language=req.language,
                text="",
                blocks=[],
            )
            for key in req.frame_keys
        ]
        return OCRResponse(results=results)

    # Real engine dispatch (Phase D). Lazy import keeps stub mode lightweight.
    from app import ocr_engine

    raw_results = ocr_engine.ocr_frames(
        frame_paths=resolved_paths,
        frame_keys=req.frame_keys,
        language=req.language,
    )
    return OCRResponse(results=[OCRFrameResult(**r) for r in raw_results])


# ---------------------------------------------------------------------------
# Custom exception handler so HTTPException(detail=ErrorResponse) renders as
# the bare error body (not nested under "detail"). Keeps the contract clean.
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "category" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})
