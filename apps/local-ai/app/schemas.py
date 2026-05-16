"""Pydantic schemas shared by local-ai endpoints.

These mirror (intentionally, by hand) the request/response models used by
`apps/api/app/ai/local_models.py`. Keeping the two in sync is a code-review
contract; see Phase B plan section "API client scaffolding".
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    ok: bool = True


# ---------------------------------------------------------------------------
# /transcribe
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    audio_key: str = Field(min_length=1)
    language: str | None = None


class TranscribeSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    text: str
    language: str | None
    segments: list[TranscribeSegment] = Field(default_factory=list)
    engine: str
    model: str


# ---------------------------------------------------------------------------
# /ocr
# ---------------------------------------------------------------------------


class OCRRequest(BaseModel):
    frame_keys: list[str] = Field(min_length=1)
    language: str | None = None


class OCRBBox(BaseModel):
    """Pixel-space bounding box, top-left origin."""
    x: int
    y: int
    w: int
    h: int


class OCRBlock(BaseModel):
    text: str
    confidence: float | None = None       # normalized 0..1
    bbox: OCRBBox | None = None


class OCRFrameResult(BaseModel):
    frame_key: str
    engine: str
    model: str
    language: str | None
    text: str
    blocks: list[OCRBlock] = Field(default_factory=list)


class OCRResponse(BaseModel):
    results: list[OCRFrameResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
#
# Returned with HTTP 400 / 404. Messages are intentionally generic so we do
# not echo client-supplied paths in error bodies (only safe categories).
# ---------------------------------------------------------------------------


ErrorCategory = Literal["invalid_key", "not_found", "internal"]


class ErrorResponse(BaseModel):
    category: ErrorCategory
    message: str
