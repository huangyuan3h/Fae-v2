"""Tests for /api/tts/speak and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.tts.speakable import clip_for_local_tts, to_speakable_text
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


def test_to_speakable_skips_tables_and_code() -> None:
    raw = (
        "地球概况如下。\n\n"
        "| 项目 | 数据 |\n| --- | --- |\n| 直径 | 1万公里 |\n\n"
        "继续说明气候。\n"
        "```js\nconsole.log(1)\n```\n"
        "结束。"
    )
    out = to_speakable_text(raw)
    assert "直径" not in out
    assert "console" not in out
    assert "地球概况" in out
    assert "气候" in out


def test_clip_for_local_tts_sentence() -> None:
    long = "第一句。" + ("字" * 200)
    out = clip_for_local_tts(long, max_chars=40)
    assert "第一句。" in out or len(out) <= 41


def test_speak_local_unavailable(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:59999/v1")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/api/tts/speak", json={"text": "你好"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "local_tts_unavailable"
    assert "59999" in body["detail"]["upstream"]


def test_speak_passes_speed_and_voice(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:8880/v1")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    wav = pcm16_mono_to_wav(b"\x00\x00" * 240, sample_rate=24000)
    mock = AsyncMock(return_value=(wav, "audio/wav"))
    with patch("fae.api.tts.LocalTTSClient.synthesize", new=mock):
        client = TestClient(create_app())
        resp = client.post(
            "/api/tts/speak",
            json={
                "text": "你好呀",
                "voice": "Ryan",
                "speed": 1.4,
                "language": "Chinese",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("x-fae-tts-voice") == "Ryan"
    assert resp.headers.get("x-fae-tts-speed") == "1.40"
    mock.assert_awaited()
    kwargs = mock.await_args.kwargs
    assert kwargs["voice"] == "Ryan"
    assert kwargs["speed"] == 1.4
    assert kwargs["language"] == "Chinese"


def test_speak_local_returns_audio(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:8880/v1")
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
    assert "8880" in (resp.headers.get("x-fae-tts-upstream") or "")


def test_tts_status_reports_upstream(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:8880/v1")
    monkeypatch.setenv("TTS_SPEED", "1.2")
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
    assert body["url"] == "http://127.0.0.1:8880/v1"
    assert body["speech_url"].endswith("/audio/speech")
    assert body["speed"] == 1.2


def test_tts_voices_builtin_fallback(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("VLLM_TTS_URL", "http://127.0.0.1:59999/v1")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/api/tts/voices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voices"]
    assert body["source"] == "builtin"
    assert "defaults" in body
