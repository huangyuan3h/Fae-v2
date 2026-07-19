"""Tests for Qwen3ASRService against a mocked HTTP backend."""

from __future__ import annotations

import httpx
import pytest

from fae.pipecat.services.qwen3_asr import Qwen3ASRService


@pytest.mark.asyncio
async def test_asr_transcribe_posts_multipart() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/audio/transcriptions")
        return httpx.Response(200, json={"text": "你好", "model": "asr-stub"})

    transport = httpx.MockTransport(handler)
    service = Qwen3ASRService("http://asr.test")

    # Patch the AsyncClient used inside transcribe by monkeypatching httpx.
    real_client = httpx.AsyncClient
    try:

        def _client(*_a, **_kw):  # noqa: ANN001
            return real_client(transport=transport, timeout=5.0)

        import fae.pipecat.services.qwen3_asr as asr_mod

        asr_mod.httpx.AsyncClient = _client  # type: ignore[assignment]
        text = await service.transcribe(b"fake-wav-bytes")
    finally:
        asr_mod.httpx.AsyncClient = real_client  # type: ignore[assignment]

    assert text == "你好"
