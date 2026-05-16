"""Async HTTP client for the internal local-ai service.

Phase B scaffolding only — NOT wired into the pipeline yet. The real
hookup happens in Phase C (transcribe_local stage) and Phase D
(ocr_frames_local stage).

Design notes:
- Uses `httpx.AsyncClient`. A transport can be injected for tests
  (see :func:`build_client`) without monkey-patching the network.
- Errors are surfaced as :class:`LocalAIError` subclasses so callers
  can distinguish 4xx contract violations from 5xx / network faults.
- Never logs request bodies or response bodies (they may contain
  storage keys); only logs the endpoint and status code.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.ai.local_models import (
    HealthResponse,
    LocalAIErrorBody,
    OCRRequest,
    OCRResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from app.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LocalAIError(RuntimeError):
    """Base class for local-ai client errors."""


class LocalAIInvalidKeyError(LocalAIError):
    """Server rejected a storage key (HTTP 400 invalid_key)."""


class LocalAINotFoundError(LocalAIError):
    """Server could not resolve a storage key to an existing file (HTTP 404)."""


class LocalAITransportError(LocalAIError):
    """Network failure, timeout, or unexpected server status."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _build_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        settings.local_ai_timeout_seconds,
        connect=settings.local_ai_connect_timeout_sec,
    )


def build_client(
    *,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.AsyncClient:
    """Construct an `httpx.AsyncClient` configured for local-ai.

    Exposed so tests can inject `httpx.MockTransport` and exercise the
    client without a network.
    """
    return httpx.AsyncClient(
        base_url=(base_url or settings.local_ai_base_url).rstrip("/"),
        timeout=timeout or _build_timeout(),
        transport=transport,
    )


def _interpret_error(response: httpx.Response) -> LocalAIError:
    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except ValueError:
        body = None

    category: str | None = None
    if isinstance(body, dict):
        try:
            category = LocalAIErrorBody.model_validate(body).category
        except Exception:  # noqa: BLE001
            category = body.get("category") if isinstance(body, dict) else None

    if response.status_code == 400 or category == "invalid_key":
        return LocalAIInvalidKeyError(f"local-ai rejected key (status={response.status_code})")
    if response.status_code == 404 or category == "not_found":
        return LocalAINotFoundError(f"local-ai key not found (status={response.status_code})")
    return LocalAITransportError(f"local-ai unexpected status {response.status_code}")


class LocalAIClient:
    """Thin async client over the local-ai HTTP contract."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or build_client(
            base_url=base_url, transport=transport, timeout=timeout
        )

    async def __aenter__(self) -> "LocalAIClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def health(self) -> HealthResponse:
        try:
            response = await self._client.get("/health")
        except httpx.HTTPError as exc:
            raise LocalAITransportError(f"health request failed: {exc!s}") from exc
        if response.status_code != 200:
            raise _interpret_error(response)
        return HealthResponse.model_validate(response.json())

    async def transcribe(
        self, *, audio_key: str, language: str | None = None
    ) -> TranscribeResponse:
        payload = TranscribeRequest(audio_key=audio_key, language=language).model_dump()
        try:
            response = await self._client.post("/transcribe", json=payload)
        except httpx.HTTPError as exc:
            raise LocalAITransportError(f"transcribe request failed: {exc!s}") from exc
        if response.status_code != 200:
            raise _interpret_error(response)
        return TranscribeResponse.model_validate(response.json())

    async def ocr(
        self, *, frame_keys: list[str], language: str | None = None
    ) -> OCRResponse:
        payload = OCRRequest(frame_keys=frame_keys, language=language).model_dump()
        try:
            response = await self._client.post("/ocr", json=payload)
        except httpx.HTTPError as exc:
            raise LocalAITransportError(f"ocr request failed: {exc!s}") from exc
        if response.status_code != 200:
            raise _interpret_error(response)
        return OCRResponse.model_validate(response.json())
