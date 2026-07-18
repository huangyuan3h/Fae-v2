"""Unit tests for DashScopeTTSService silent fallback."""

from __future__ import annotations

import pytest

from fae.pipecat.services.dashscope_tts import DashScopeTTSService
from fae.pipecat.services.qwen3_tts import Qwen3TTSService


@pytest.mark.asyncio
async def test_dashscope_tts_silent_without_key() -> None:
    tts = DashScopeTTSService(api_key="")
    frames = []
    async for frame in tts.run_tts("你好", context_id="ctx-1"):
        if frame is not None:
            frames.append(frame)
    assert frames
    assert getattr(frames[0], "audio", b"")


@pytest.mark.asyncio
async def test_qwen3_tts_silent_without_key() -> None:
    tts = Qwen3TTSService(api_key="")
    pcm = await tts.synthesize("测试")
    assert len(pcm) > 0
