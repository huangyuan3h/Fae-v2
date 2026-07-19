"""Tests for /api/tts/speak and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.tts.speakable import to_speakable_text
from fae.tts.wav import pcm16_mono_to_wav


def test_pcm_to_wav_header() -> None:
    pcm = b"\x00\x01" * 100
    wav = pcm16_mono_to_wav(pcm, sample_rate=24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav.endswith(pcm)


def test_to_speakable_strips_markdown_and_think() -> None:
    raw = "<think>plan</think>\n# 标题\n**你好**世界"
    assert to_speakable_text(raw) == "标题\n你好世界"


def test_speak_requires_dashscope_key(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/api/tts/speak", json={"text": "你好"})
    assert resp.status_code == 503


def test_speak_returns_wav(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    fake_pcm = b"\x00\x00" * 240  # 10ms @ 24kHz
    with patch(
        "fae.api.tts.Qwen3TTSService.synthesize",
        new=AsyncMock(return_value=fake_pcm),
    ):
        client = TestClient(create_app())
        resp = client.post("/api/tts/speak", json={"text": "你好呀"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert resp.content[:4] == b"RIFF"


def test_tts_status(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/api/tts/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["backend"] == "qwen3-tts"
