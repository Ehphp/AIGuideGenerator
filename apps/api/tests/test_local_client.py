"""Phase B: api-side LocalAIClient against a mocked local-ai service."""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.ai.local_client import (
    LocalAIClient,
    LocalAIInvalidKeyError,
    LocalAINotFoundError,
    LocalAITransportError,
)


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_health_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True})

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        h = await client.health()
        assert h.ok is True


@pytest.mark.asyncio
async def test_transcribe_success():
    sid = str(uuid.uuid4())
    expected_key = f"sessions/{sid}/audio.wav"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcribe"
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["audio_key"] == expected_key
        assert body["language"] == "it"
        return httpx.Response(
            200,
            json={
                "text": "",
                "language": "it",
                "segments": [],
                "engine": "stub",
                "model": "stub",
            },
        )

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        r = await client.transcribe(audio_key=expected_key, language="it")
        assert r.text == ""
        assert r.language == "it"
        assert r.engine == "stub"
        assert r.model == "stub"
        assert r.segments == []


@pytest.mark.asyncio
async def test_ocr_success():
    sid = str(uuid.uuid4())
    keys = [
        f"sessions/{sid}/frames/frame_0001.jpg",
        f"sessions/{sid}/frames/frame_0002.jpg",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ocr"
        body = json.loads(request.content)
        assert body["frame_keys"] == keys
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "frame_key": k,
                        "engine": "stub",
                        "model": "stub",
                        "language": "it",
                        "text": "",
                        "blocks": [],
                    }
                    for k in keys
                ]
            },
        )

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        r = await client.ocr(frame_keys=keys, language="it")
        assert len(r.results) == 2
        assert [x.frame_key for x in r.results] == keys


@pytest.mark.asyncio
async def test_invalid_key_raises_typed_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"category": "invalid_key", "message": "bad"}
        )

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        with pytest.raises(LocalAIInvalidKeyError):
            await client.transcribe(audio_key="../etc/passwd")


@pytest.mark.asyncio
async def test_not_found_raises_typed_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"category": "not_found", "message": "missing"}
        )

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        with pytest.raises(LocalAINotFoundError):
            await client.ocr(frame_keys=["sessions/x/frames/frame_0001.jpg"])


@pytest.mark.asyncio
async def test_5xx_raises_transport_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        with pytest.raises(LocalAITransportError):
            await client.health()


@pytest.mark.asyncio
async def test_network_failure_raises_transport_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conn refused")

    async with LocalAIClient(transport=_mock_transport(handler)) as client:
        with pytest.raises(LocalAITransportError):
            await client.health()


@pytest.mark.asyncio
async def test_client_is_not_wired_into_factory():
    # Phase B requirement: getters must NOT yet route to local-ai. Confirm
    # the per-capability getters still return the existing AIProvider, not
    # a LocalAIClient.
    from app.ai import get_ocr_provider, get_stt_provider

    stt = get_stt_provider()
    ocr = get_ocr_provider()
    assert not isinstance(stt, LocalAIClient)
    assert not isinstance(ocr, LocalAIClient)
