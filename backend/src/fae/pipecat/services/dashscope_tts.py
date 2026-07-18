"""DashScope / Qwen3 TTS as a Pipecat TTSService.

Uses MultiModalConversation (qwen3-tts-flash) streaming PCM when a key is
configured; falls back to silent PCM for hermetic tests.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncGenerator

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

logger = logging.getLogger("fae.pipecat.tts")


class DashScopeTTSService(TTSService):
    """Pipecat TTS backed by DashScope Qwen3-TTS."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        sample_rate: int = 24000,
        language_type: str = "Chinese",
        **kwargs,
    ) -> None:
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._language_type = language_type
        self._fallback_rate = sample_rate

    async def run_tts(
        self, text: str, context_id: str
    ) -> AsyncGenerator[Frame | None, None]:
        if not text.strip():
            return
        rate = self.sample_rate or self._fallback_rate
        if not self._api_key:
            # Silent fallback — keeps pipelines testable offline.
            silence = b"\x00\x00" * max(1, int(rate * 0.05))
            yield TTSAudioRawFrame(
                audio=silence,
                sample_rate=rate,
                num_channels=1,
                context_id=context_id,
            )
            return

        try:
            import dashscope

            # Beijing region default; override via DASHSCOPE_HTTP_BASE_URL if needed.
            response = dashscope.MultiModalConversation.call(
                api_key=self._api_key,
                model=self._model,
                text=text,
                voice=self._voice,
                language_type=self._language_type,
                stream=True,
            )
            async for chunk in _aiter_sync(response):
                if chunk is None or getattr(chunk, "output", None) is None:
                    continue
                audio = chunk.output.audio
                data_b64 = getattr(audio, "data", None) if audio else None
                if not data_b64:
                    continue
                pcm = base64.b64decode(data_b64)
                if pcm:
                    yield TTSAudioRawFrame(
                        audio=pcm,
                        sample_rate=rate,
                        num_channels=1,
                        context_id=context_id,
                    )
        except Exception as e:  # noqa: BLE001
            logger.exception("DashScope TTS failed")
            yield ErrorFrame(error=f"DashScope TTS error: {e}")


async def _aiter_sync(iterable):
    """Wrap a sync generator/iterable for async for."""
    for item in iterable:
        yield item
