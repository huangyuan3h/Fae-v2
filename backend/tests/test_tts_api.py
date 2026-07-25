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


# --- Voice hygiene: emoji / laughs / singsong punctuation --------------------


def test_to_speakable_strips_emoji_runs() -> None:
    raw = "好的没问题😄😂🤣，我马上看一下🙂"
    out = to_speakable_text(raw)
    assert "好的没问题" in out
    assert "我马上看一下" in out
    # No codepoint escapes leaked; no ZWJ or emoji ranges left.
    for ch in out:
        assert ord(ch) < 0x2600 or 0x2700 <= ord(ch) < 0x1F300, (
            f"residual emoji codepoint U+{ord(ch):04X} in {out!r}"
        )


def test_to_speakable_strips_emoji_in_thinking_block() -> None:
    raw = "做完了😊\n\n下一步可以试试更复杂的方案🚀"
    out = to_speakable_text(raw)
    assert "做完了" in out
    assert "下一步可以试试更复杂的方案" in out
    assert "😊" not in out
    assert "🚀" not in out


def test_to_speakable_drops_english_laugh_fillers() -> None:
    raw = "Oh haha haha that's funny lol 😂"
    out = to_speakable_text(raw)
    # Drop the runs of emoji + fillers, keep the words around them.
    assert "haha" not in out.lower()
    assert "lol" not in out.lower()
    assert "that's" in out or "funny" in out


def test_to_speakable_drops_ascii_kaomoji_and_wavy() -> None:
    raw = "嗯嗯好的~~~~ :) 我们继续吧"
    out = to_speakable_text(raw)
    assert ":)" not in out
    assert "~" not in out
    assert "嗯嗯好的" in out
    assert "我们继续吧" in out


def test_to_speakable_drops_parenthesised_kaomoji() -> None:
    raw = "好开心(*^▽^*) (T_T) 又被感动了"
    out = to_speakable_text(raw)
    assert "*^▽^*" not in out
    assert "(T_T)" not in out
    assert "好开心" in out
    assert "又被感动了" in out


def test_to_speakable_preserves_bracketed_nouns() -> None:
    # Plain "(八百米)" / "(function)" should NOT be classified as kaomoji.
    out1 = to_speakable_text("(八百米)决赛开始了")
    assert "(八百米)" in out1
    out2 = to_speakable_text("这段代码 (function) 很奇怪")
    assert "(function)" in out2


def test_to_speakable_collapses_singsong_punctuation() -> None:
    raw = "真的吗？？？？！！！不敢相信！！！"
    out = to_speakable_text(raw)
    # Each duplicate run collapses to a single mark.
    assert "？？？？" not in out
    assert "！！！" not in out
    assert "真的吗？" in out


def test_to_speakable_strips_invisible_chars() -> None:
    raw = "你好\u200d世界\u200b测试"
    out = to_speakable_text(raw)
    # ZWJ / ZWSP replaced by space and collapsed; no orphan invisibles.
    for ch in out:
        assert ch not in ("\u200d", "\u200b", "\u2060")


def test_to_speakable_keeps_chinese_punctuation_unchanged() -> None:
    raw = "你好。吃饭了吗？我们出发吧！"
    out = to_speakable_text(raw)
    # Sentence-ending CJK punctuation survives; we only collapse LATER duplicates.
    assert "你好。" in out
    assert "我们出发吧！" in out


def test_to_speakable_handles_empty_and_only_noise() -> None:
    assert to_speakable_text("") == ""
    assert to_speakable_text("😀🤣") == ""
    assert to_speakable_text("   \n\n  ") == ""


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
    with (
        patch(
            "fae.api.tts.LocalTTSClient.health",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "fae.api.tts.LocalTTSClient.upstream_status",
            new=AsyncMock(
                return_value={
                    "status": "healthy",
                    "backend": {
                        "name": "mlx",
                        "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
                    },
                    "device": {"type": "metal"},
                }
            ),
        ),
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
    assert body["upstream_engine"] == "mlx"
    assert "1.7B" in body["upstream_model"]
    assert body["upstream_device"] == "metal"


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
