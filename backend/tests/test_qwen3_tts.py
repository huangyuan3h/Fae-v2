"""Tests for Qwen3TTSService offline stub."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from fae.pipecat.services.qwen3_tts import Qwen3TTSService
from fae.tts.wav import pcm16_mono_to_wav


@pytest.mark.asyncio
async def test_tts_stub_returns_pcm_proportional_to_text() -> None:
    tts = Qwen3TTSService(base_url="")
    silence = await tts.synthesize("abcd")
    assert len(silence) > 0
    assert len(silence) % 2 == 0  # PCM16
    assert await tts.synthesize("   ") == b""


@pytest.mark.asyncio
async def test_qwen3_tts_strips_emoji_before_synth() -> None:
    wav = pcm16_mono_to_wav(b"\x00\x00" * 40, sample_rate=24000)
    mock = AsyncMock(return_value=(wav, "audio/wav"))
    with patch(
        "fae.pipecat.services.qwen3_tts.LocalTTSClient.synthesize",
        new=mock,
    ):
        tts = Qwen3TTSService(base_url="http://tts.test/v1")
        pcm = await tts.synthesize("哈哈😂😂我们继续")
    assert pcm == wav[44:]
    sent = mock.await_args.args[0]
    assert "😂" not in sent
    assert "哈哈" in sent


@pytest.mark.asyncio
async def test_qwen3_tts_can_disable_stripper() -> None:
    wav = pcm16_mono_to_wav(b"\x00\x00" * 40, sample_rate=24000)
    mock = AsyncMock(return_value=(wav, "audio/wav"))
    with patch(
        "fae.pipecat.services.qwen3_tts.LocalTTSClient.synthesize",
        new=mock,
    ):
        tts = Qwen3TTSService(base_url="http://tts.test/v1", strip_speakable=False)
        await tts.synthesize("哈哈😂")
    sent = mock.await_args.args[0]
    assert "😂" in sent
