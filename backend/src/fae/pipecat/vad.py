"""VAD helpers — EnergyVAD fallback + Silero when pipecat-ai[silero] is present."""

from __future__ import annotations

import logging
import struct
from typing import Any, Protocol

logger = logging.getLogger("fae.pipecat.vad")


class VADAnalyzer(Protocol):
    def is_speech(self, pcm16_mono: bytes) -> bool: ...


def _pcm16_rms(pcm16_mono: bytes) -> float:
    if len(pcm16_mono) < 2:
        return 0.0
    n = len(pcm16_mono) // 2
    samples = struct.unpack(f"<{n}h", pcm16_mono[: n * 2])
    acc = sum(s * s for s in samples)
    return (acc / n) ** 0.5


class EnergyVAD:
    """Simple energy-based VAD used by tests and offline stubs."""

    def __init__(self, threshold: int = 500) -> None:
        self._threshold = threshold

    def is_speech(self, pcm16_mono: bytes) -> bool:
        if not pcm16_mono:
            return False
        return _pcm16_rms(pcm16_mono) >= self._threshold


def try_silero_vad(**kwargs: Any) -> Any | None:
    """Return a Pipecat SileroVADAnalyzer, or None if unavailable."""
    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.audio.vad.vad_analyzer import VADParams

        params = kwargs.pop("params", VADParams(stop_secs=0.2))
        analyzer = SileroVADAnalyzer(params=params, **kwargs)
        logger.info("Silero VAD ready")
        return analyzer
    except Exception:  # noqa: BLE001
        logger.debug("Silero VAD unavailable", exc_info=True)
        return None


def default_vad() -> Any:
    """Prefer Silero; fall back to EnergyVAD."""
    return try_silero_vad() or EnergyVAD()
