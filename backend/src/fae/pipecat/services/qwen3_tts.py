"""Qwen3-TTS service (standalone + DashScope).

Used by TextPipelineBot. When `api_key` is set, synthesizes via DashScope
qwen3-tts-flash; otherwise returns short silent PCM for offline tests.
"""

from __future__ import annotations

import base64
import logging
import struct

logger = logging.getLogger("fae.pipecat.tts")


class Qwen3TTSService:
    def __init__(
        self,
        api_key: str = "",
        sample_rate: int = 24000,
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        language_type: str = "Chinese",
    ) -> None:
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._model = model
        self._voice = voice
        self._language_type = language_type

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def synthesize(
        self, text: str, *, raise_on_error: bool = False
    ) -> bytes:
        if not text.strip():
            return b""
        if not self._api_key:
            if raise_on_error:
                raise RuntimeError("DashScope API key not configured")
            frames = max(1, len(text) * int(self._sample_rate * 0.04))
            return struct.pack(f"<{frames}h", *([0] * frames))

        try:
            import dashscope

            chunks: list[bytes] = []
            response = dashscope.MultiModalConversation.call(
                api_key=self._api_key,
                model=self._model,
                text=text,
                voice=self._voice,
                language_type=self._language_type,
                stream=True,
            )
            for chunk in response:
                if chunk is None or getattr(chunk, "output", None) is None:
                    continue
                audio = chunk.output.audio
                data_b64 = getattr(audio, "data", None) if audio else None
                if data_b64:
                    chunks.append(base64.b64decode(data_b64))
            pcm = b"".join(chunks)
            logger.debug("DashScope TTS bytes=%d text=%r", len(pcm), text[:40])
            if raise_on_error and not pcm:
                raise RuntimeError("Qwen3-TTS returned empty audio")
            return pcm
        except Exception:
            if raise_on_error:
                raise
            logger.exception("DashScope TTS failed — returning silence")
            frames = max(1, int(self._sample_rate * 0.1))
            return struct.pack(f"<{frames}h", *([0] * frames))
