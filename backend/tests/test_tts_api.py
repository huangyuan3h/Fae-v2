"""Tests for /api/tts/speak and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.tts.speakable import to_speakable_text
from fae.tts.wav import pcm16_mono_to_wav, wav_to_pcm16_mono


def test_pcm_to_wav_header() -> None:
    pcm = b"\x00\x01" * 100
    wav = pcm16_mono_to_wav(pcm, sample_rate=24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav.endswith(pcm)
    assert wav_to_pcm16_mono(wav) == pcm
    assert wav_to_pcm16_mono(b"") == b""
    assert wav_to_pcm16_mono(b"not-riff") == b"not-riff"
    assert pcm16_mono_to_wav(b"") == b""


def test_to_speakable_strips_markdown_and_think() -> None:
    raw = "<think>plan</think>\n# 标题\n**你好**世界"
    assert to_speakable_text(raw) == "标题\n你好世界"


def test_speak_embedded_stub(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TTS_EMBED_STUB", "true")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/api/tts/speak", json={"text": "你好呀"})
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"
    assert resp.headers.get("x-fae-tts-backend") == "local-embedded"
    # OpenAI-compatible route also mounted
    assert client.get("/v1/models").status_code == 200
    speech = client.post(
        "/v1/audio/speech",
        json={"input": "hi", "voice": "Cherry", "model": "qwen3-tts"},
    )
    assert speech.status_code == 200
    assert speech.content[:4] == b"RIFF"


def test_speak_local_unavailable(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TTS_EMBED_STUB", "false")
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:59999/v1")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/api/tts/speak", json={"text": "你好"})
    assert resp.status_code == 503


def test_speak_local_returns_audio(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TTS_EMBED_STUB", "false")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    wav = pcm16_mono_to_wav(b"\x00\x00" * 240, sample_rate=24000)
    with patch(
        "fae.api.tts.LocalTTSClient.synthesize",
        new=AsyncMock(return_value=(wav, "audio/wav")),
    ):
        client = TestClient(create_app())
        resp = client.post("/api/tts/speak", json={"text": "你好呀"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert resp.content[:4] == b"RIFF"
    assert resp.headers.get("x-fae-tts-backend") == "local"


def test_tts_status_embedded(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TTS_EMBED_STUB", "true")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/api/tts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "local"
    assert body["configured"] is True
    assert body["embedded"] is True
    assert body["natural_speech"] is False


def test_tts_status_external(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TTS_EMBED_STUB", "false")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    with patch(
        "fae.api.tts.LocalTTSClient.health",
        new=AsyncMock(return_value=True),
    ):
        client = TestClient(create_app())
        resp = client.get("/api/tts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "local"
    assert body["configured"] is True
    assert body["embedded"] is False
