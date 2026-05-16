"""Factory for AIProvider based on settings.ai_provider."""
from __future__ import annotations

from app.ai.base import AIProvider
from app.config import settings


def get_ai_provider() -> AIProvider:
    name = (settings.ai_provider or "openai").lower()
    if name == "fake":
        from app.ai.fake_provider import FakeAIProvider

        return FakeAIProvider()
    if name == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider()
    raise ValueError(f"unknown AI provider: {name!r}")


# ---------------------------------------------------------------------------
# Per-capability getters (Phase A scaffolding).
#
# These intentionally delegate to the existing monolithic provider so Phase A
# introduces NO behavior change. Phases C / D / E will replace each one with
# the appropriate local-ai or sanitized-LLM client based on the
# `stt_provider`, `ocr_provider`, and `guide_llm_provider` settings.
# ---------------------------------------------------------------------------


def get_stt_provider() -> AIProvider:
    """Speech-to-text provider. Phase C will route 'local' to LocalAIClient."""
    return get_ai_provider()


def get_ocr_provider() -> AIProvider:
    """OCR provider. Phase D will route 'local' to LocalAIClient."""
    return get_ai_provider()


def get_guide_llm_provider() -> AIProvider:
    """External LLM used by generate_guide / validate_guide. Always external."""
    return get_ai_provider()
