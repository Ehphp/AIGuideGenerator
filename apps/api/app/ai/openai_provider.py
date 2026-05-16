"""OpenAI implementation of AIProvider (Whisper + GPT-4o vision)."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.ai.base import (
    AIProvider,
    FrameAnalysis,
    TextResult,
    TranscriptionResult,
    TranscriptSegment,
)
from app.config import settings

log = logging.getLogger(__name__)


def _client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return AsyncOpenAI(api_key=settings.openai_api_key)


class OpenAIProvider(AIProvider):
    async def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> TranscriptionResult:
        client = _client()
        kwargs: dict[str, Any] = {
            "model": settings.openai_stt_model,
            "response_format": "verbose_json",
        }
        if language:
            kwargs["language"] = language
        with audio_path.open("rb") as fh:
            resp = await client.audio.transcriptions.create(file=fh, **kwargs)

        # SDK returns a Pydantic model; coerce to dict for storage.
        raw = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        segments = []
        for seg in raw.get("segments") or []:
            segments.append(
                TranscriptSegment(
                    start=float(seg.get("start", 0.0)),
                    end=float(seg.get("end", 0.0)),
                    text=str(seg.get("text", "")),
                )
            )
        return TranscriptionResult(
            text=str(raw.get("text", "")),
            language=raw.get("language"),
            segments=segments,
            raw=raw,
            audio_duration_sec=raw.get("duration"),
            model=settings.openai_stt_model,
        )

    async def analyze_frame(
        self, image_path: Path, *, prompt: str
    ) -> FrameAnalysis:
        client = _client()
        mime, _ = mimetypes.guess_type(str(image_path))
        if not mime:
            mime = "image/jpeg"
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        resp = await client.chat.completions.create(
            model=settings.openai_vision_model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        raw = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        content = ""
        try:
            content = resp.choices[0].message.content or ""
        except Exception:
            content = ""

        ocr_text = ""
        ui_summary = ""
        try:
            data = json.loads(content) if content else {}
            ocr_text = str(data.get("ocr_text", ""))
            ui_summary = str(data.get("ui_summary", ""))
        except json.JSONDecodeError:
            log.warning("vision response was not valid JSON; storing raw")
            ui_summary = content

        usage = raw.get("usage") or {}
        return FrameAnalysis(
            ocr_text=ocr_text,
            ui_summary=ui_summary,
            raw=raw,
            input_chars=int(usage.get("prompt_tokens", 0)),
            output_chars=int(usage.get("completion_tokens", 0)),
            model=settings.openai_vision_model,
        )

    async def generate_json(self, *, prompt: str) -> TextResult:
        client = _client()
        resp = await client.chat.completions.create(
            model=settings.openai_llm_model,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        try:
            text = resp.choices[0].message.content or ""
        except Exception:
            text = ""
        usage = raw.get("usage") or {}
        return TextResult(
            text=text,
            raw=raw,
            input_chars=int(usage.get("prompt_tokens", 0)),
            output_chars=int(usage.get("completion_tokens", 0)),
            model=settings.openai_llm_model,
        )
