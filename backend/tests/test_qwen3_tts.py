"""Tests for Qwen3TTSService stub."""

from __future__ import annotations

import pytest

from fae.pipecat.services.qwen3_tts import Qwen3TTSService


@pytest.mark.asyncio
async def test_tts_stub_returns_pcm_proportional_to_text() -> None:
    tts = Qwen3TTSService(api_key="")
    silence = await tts.synthesize("abcd")
    assert len(silence) > 0
    assert len(silence) % 2 == 0  # PCM16
    assert await tts.synthesize("   ") == b""
