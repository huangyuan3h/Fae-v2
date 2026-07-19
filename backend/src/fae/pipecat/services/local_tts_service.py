"""Pipecat TTSService backed by local OpenAI-compatible TTS."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.wav import wav_to_pcm16_mono

logger = logging.getLogger("fae.pipecat.tts")


class LocalTTSService(TTSService):
    """Pipecat TTS using VLLM_TTS_URL (Qwen3-TTS / CosyVoice / stub)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "qwen3-tts",
        voice: str = "Cherry",
        sample_rate: int = 24000,
        response_format: str = "wav",
        timeout_s: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._base_url = (base_url or "").strip()
        self._model = model
        self._voice = voice
        self._fallback_rate = sample_rate
        self._response_format = response_format
        self._timeout_s = timeout_s

    async def run_tts(
        self, text: str, context_id: str
    ) -> AsyncGenerator[Frame | None, None]:
        if not text.strip():
            return
        rate = self.sample_rate or self._fallback_rate
        if not self._base_url:
            silence = b"\x00\x00" * max(1, int(rate * 0.05))
            yield TTSAudioRawFrame(
                audio=silence,
                sample_rate=rate,
                num_channels=1,
                context_id=context_id,
            )
            return

        client = LocalTTSClient(
            base_url=self._base_url,
            model=self._model,
            voice=self._voice,
            sample_rate=rate,
            response_format=self._response_format,
            timeout_s=self._timeout_s,
        )
        try:
            audio, _ctype = await client.synthesize(text, voice=self._voice)
            pcm = wav_to_pcm16_mono(audio)
            if not pcm:
                silence = b"\x00\x00" * max(1, int(rate * 0.05))
                pcm = silence
            yield TTSAudioRawFrame(
                audio=pcm,
                sample_rate=rate,
                num_channels=1,
                context_id=context_id,
            )
        except LocalTTSError as e:
            logger.exception("Local TTS failed")
            yield ErrorFrame(error=f"Local TTS error: {e}")
        except Exception as e:  # noqa: BLE001
            logger.exception("Local TTS failed")
            yield ErrorFrame(error=f"Local TTS error: {e}")
