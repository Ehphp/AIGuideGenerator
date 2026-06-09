"""AI provider interface used by pipeline stages."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    segments: list[TranscriptSegment]
    raw: dict[str, Any] = field(default_factory=dict)
    # Usage accounting (best-effort).
    audio_duration_sec: float | None = None
    model: str = ""


@dataclass
class FrameAnalysis:
    ocr_text: str
    ui_summary: str
    raw: dict[str, Any] = field(default_factory=dict)
    input_chars: int = 0
    output_chars: int = 0
    model: str = ""


@dataclass
class TextResult:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    input_chars: int = 0
    output_chars: int = 0
    model: str = ""


class AIProvider(ABC):
    @abstractmethod
    async def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> TranscriptionResult: ...

    @abstractmethod
    async def analyze_frame(
        self, image_path: Path, *, prompt: str
    ) -> FrameAnalysis: ...

    @abstractmethod
    async def generate_json(
        self,
        *,
        prompt: str,
        max_completion_tokens: int | None = None,
    ) -> TextResult:
        """LLM call returning a JSON-formatted text payload."""
