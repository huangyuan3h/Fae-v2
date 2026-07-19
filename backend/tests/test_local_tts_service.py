"""Unit tests for Pipecat LocalTTSService + Qwen3TTSService local path."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

from fae.pipecat.services.local_tts_service import LocalTTSService
from fae.pipecat.services.qwen3_tts import Qwen3TTSService
from fae.tts.local_client import LocalTTSError
from fae.tts.wav import pcm16_mono_to_wav


@pytest.mark.asyncio
async def test_local_tts_service_silent_without_url() -> None:
    tts = LocalTTSService(base_url="")
    frames = [f async for f in tts.run_tts("hello", "ctx")]
    assert len(frames) == 1
    assert isinstance(frames[0], TTSAudioRawFrame)
    assert frames[0].audio


@pytest.mark.asyncio
async def test_local_tts_service_empty_text() -> None:
    tts = LocalTTSService(base_url="http://tts.test/v1")
    frames = [f async for f in tts.run_tts("   ", "ctx")]
    assert frames == []


@pytest.mark.asyncio
async def test_local_tts_service_success() -> None:
    wav = pcm16_mono_to_wav(b"\x00\x01" * 40, sample_rate=24000)
    tts = LocalTTSService(base_url="http://tts.test/v1")
    with patch(
        "fae.pipecat.services.local_tts_service.LocalTTSClient.synthesize",
        new=AsyncMock(return_value=(wav, "audio/wav")),
    ):
        frames = [f async for f in tts.run_tts("你好", "ctx")]
    assert len(frames) == 1
    assert isinstance(frames[0], TTSAudioRawFrame)
    assert frames[0].audio == b"\x00\x01" * 40


@pytest.mark.asyncio
async def test_local_tts_service_error_frame() -> None:
    tts = LocalTTSService(base_url="http://tts.test/v1")
    with patch(
        "fae.pipecat.services.local_tts_service.LocalTTSClient.synthesize",
        new=AsyncMock(side_effect=LocalTTSError("down")),
    ):
        frames = [f async for f in tts.run_tts("hi", "ctx")]
    assert len(frames) == 1
    assert isinstance(frames[0], ErrorFrame)


@pytest.mark.asyncio
async def test_qwen3_tts_silent_without_url() -> None:
    tts = Qwen3TTSService(base_url="")
    silence = await tts.synthesize("abcd")
    assert len(silence) > 0
    assert len(silence) % 2 == 0
    assert tts.configured is False


@pytest.mark.asyncio
async def test_qwen3_tts_local_success() -> None:
    wav = pcm16_mono_to_wav(b"\x02\x03" * 20, sample_rate=24000)
    tts = Qwen3TTSService(base_url="http://tts.test/v1")
    assert tts.configured is True
    with patch(
        "fae.pipecat.services.qwen3_tts.LocalTTSClient.synthesize",
        new=AsyncMock(return_value=(wav, "audio/wav")),
    ):
        pcm = await tts.synthesize("ok")
    assert pcm == b"\x02\x03" * 20


@pytest.mark.asyncio
async def test_qwen3_tts_raise_on_error() -> None:
    tts = Qwen3TTSService(base_url="")
    with pytest.raises(RuntimeError, match="not configured"):
        await tts.synthesize("x", raise_on_error=True)


@pytest.mark.asyncio
async def test_qwen3_tts_local_error_silence() -> None:
    tts = Qwen3TTSService(base_url="http://tts.test/v1")
    with patch(
        "fae.pipecat.services.qwen3_tts.LocalTTSClient.synthesize",
        new=AsyncMock(side_effect=LocalTTSError("down")),
    ):
        pcm = await tts.synthesize("x")
    assert len(pcm) > 0
