"""Pydantic models for the local-ai HTTP contract.

Hand-mirrored from `apps/local-ai/app/schemas.py`. Kept in this package so
api-side code can import them without a runtime dependency on the local-ai
package itself.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool


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


class OCRRequest(BaseModel):
    frame_keys: list[str] = Field(min_length=1)
    language: str | None = None


class OCRBBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class OCRBlock(BaseModel):
    text: str
    confidence: float | None = None
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


ErrorCategory = Literal["invalid_key", "not_found", "internal"]


class LocalAIErrorBody(BaseModel):
    category: ErrorCategory
    message: str
