"""Qwen3-TTS service stub.

Phase 1.3 returns silent PCM for sentence boundaries so the pipeline can
exercise barge-in / aggregator wiring without DashScope credentials.
Realtime WebSocket synthesis lands in a later checkpoint.
"""

from __future__ import annotations

import logging
import struct

logger = logging.getLogger("fae.pipecat.tts")


class Qwen3TTSService:
    def __init__(self, api_key: str = "", sample_rate: int = 24000) -> None:
        self._api_key = api_key
        self._sample_rate = sample_rate

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def synthesize(self, text: str) -> bytes:
        """Return a short silent PCM16 mono buffer sized by text length.

        Placeholder keeps the bot event loop honest without external I/O.
        """
        if not text.strip():
            return b""
        # ~40ms of silence per character — enough for tests to observe audio frames.
        frames = max(1, len(text) * int(self._sample_rate * 0.04))
        logger.debug(
            "TTS stub synthesize text=%r frames=%d configured=%s",
            text[:40],
            frames,
            self.configured,
        )
        return struct.pack(f"<{frames}h", *([0] * frames))
