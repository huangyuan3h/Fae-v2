"""Local Qwen3-TTS client for TextPipelineBot.

Calls the OpenAI-compatible local TTS server. When `base_url` is empty,
returns short silent PCM for offline / unit tests.
"""

from __future__ import annotations

import logging
import struct

from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.speakable import to_speakable_text
from fae.tts.wav import wav_to_pcm16_mono

logger = logging.getLogger("fae.pipecat.tts")


class Qwen3TTSService:
    def __init__(
        self,
        *,
        base_url: str = "",
        sample_rate: int = 24000,
        model: str = "qwen3-tts",
        voice: str = "Cherry",
        response_format: str = "wav",
        timeout_s: float = 60.0,
        # Deprecated no-op kept so older call sites / tests do not break.
        api_key: str = "",
        language_type: str = "Chinese",
        strip_speakable: bool = True,
    ) -> None:
        del api_key, language_type
        self._base_url = (base_url or "").strip()
        self._sample_rate = sample_rate
        self._model = model
        self._voice = voice
        self._response_format = response_format
        self._timeout_s = timeout_s
        # Default-on: drop emoji / markdown / singsong before hitting the
        # TTS server. The browser path already runs toSpeakableText upstream
        # — turning it off here keeps raw synthesis parity when callers want
        # to bypass the stripper (e.g. reading aloud an explicit script).
        self._strip_speakable = strip_speakable

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _silence(self, text: str) -> bytes:
        frames = max(1, len(text) * int(self._sample_rate * 0.04))
        return struct.pack(f"<{frames}h", *([0] * frames))

    async def synthesize(
        self, text: str, *, raise_on_error: bool = False
    ) -> bytes:
        if self._strip_speakable:
            text = to_speakable_text(text)
        if not text.strip():
            return b""
        if not self._base_url:
            if raise_on_error:
                raise RuntimeError("Local TTS URL not configured")
            return self._silence(text)

        client = LocalTTSClient(
            base_url=self._base_url,
            model=self._model,
            voice=self._voice,
            sample_rate=self._sample_rate,
            response_format=self._response_format,
            timeout_s=self._timeout_s,
        )
        try:
            audio, _ctype = await client.synthesize(text, voice=self._voice)
            pcm = wav_to_pcm16_mono(audio)
            logger.debug("Local TTS bytes=%d text=%r", len(pcm), text[:40])
            if raise_on_error and not pcm:
                raise RuntimeError("Local TTS returned empty audio")
            return pcm
        except LocalTTSError:
            if raise_on_error:
                raise
            logger.exception("Local TTS failed — returning silence")
            frames = max(1, int(self._sample_rate * 0.1))
            return struct.pack(f"<{frames}h", *([0] * frames))
        except Exception:
            if raise_on_error:
                raise
            logger.exception("Local TTS failed — returning silence")
            frames = max(1, int(self._sample_rate * 0.1))
            return struct.pack(f"<{frames}h", *([0] * frames))
