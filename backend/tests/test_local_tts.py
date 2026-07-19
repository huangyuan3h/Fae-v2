"""Local TTS client + stub server coverage."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.stub_server import app as stub_app
from fae.tts.wav import pcm16_mono_to_wav


def test_stub_health_and_speech() -> None:
    client = TestClient(stub_app)
    assert client.get("/health").json()["status"] == "ok"
    models = client.get("/v1/models").json()
    assert models["data"]
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "你好", "voice": "Cherry", "model": "qwen3-tts"},
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_local_client_against_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LocalTTSClient(base_url="http://tts.test/v1")
    wav = pcm16_mono_to_wav(b"\x00\x00" * 100, sample_rate=24000)

    async def fake_post(self, url, **kwargs):  # noqa: ANN001, ARG001
        return Response(200, content=wav, headers={"content-type": "audio/wav"})

    async def fake_get(self, url, **kwargs):  # noqa: ANN001, ARG001
        assert str(url).endswith("/models")
        return Response(
            200, json={"object": "list", "data": [{"id": "qwen3-tts"}]}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert await client.health() is True
    data, ctype = await client.synthesize("hello", voice="Cherry")
    assert ctype.startswith("audio/")
    assert data[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_local_client_health_ignores_generic_app_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAE /health must not count as a TTS server."""
    client = LocalTTSClient(base_url="http://127.0.0.1:8000/v1")

    async def fake_get(self, url, **kwargs):  # noqa: ANN001, ARG001
        if str(url).endswith("/models"):
            return Response(404, json={"detail": "Not Found"})
        return Response(200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert await client.health() is False


@pytest.mark.asyncio
async def test_local_client_unreachable() -> None:
    client = LocalTTSClient(
        base_url="http://127.0.0.1:59998/v1", timeout_s=0.5
    )
    with pytest.raises(LocalTTSError):
        await client.synthesize("hi")


@pytest.mark.asyncio
async def test_local_client_pcm_wrap(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LocalTTSClient(base_url="http://tts.test/v1", response_format="pcm")
    pcm = b"\x00\x00" * 50

    async def fake_post(self, url, **kwargs):  # noqa: ANN001, ARG001
        return Response(
            200, content=pcm, headers={"content-type": "audio/pcm"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    data, ctype = await client.synthesize("x")
    assert ctype == "audio/wav"
    assert data[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_local_client_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LocalTTSClient(base_url="http://tts.test/v1")

    async def fake_post(self, url, **kwargs):  # noqa: ANN001, ARG001
        return Response(500, text="boom")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(LocalTTSError, match="500"):
        await client.synthesize("x")
