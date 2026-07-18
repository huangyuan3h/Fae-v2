"""VAD helpers for Phase 1.3.

Silero VAD ships with `pipecat-ai[silero]` — optional. Until that dependency
is pinned in the default install, we expose:

1. `EnergyVAD` — lightweight RMS gate for unit tests / local stubs
2. `try_silero_vad()` — import Silero when pipecat is available

SmartTurn v3 remains a follow-up once the Daily transport path is live.
"""

from __future__ import annotations

import logging
import struct
from typing import Protocol

logger = logging.getLogger("fae.pipecat.vad")


class VADAnalyzer(Protocol):
    def is_speech(self, pcm16_mono: bytes) -> bool: ...


def _pcm16_rms(pcm16_mono: bytes) -> float:
    """RMS of little-endian PCM16 samples (avoids deprecated audioop)."""
    if len(pcm16_mono) < 2:
        return 0.0
    n = len(pcm16_mono) // 2
    samples = struct.unpack(f"<{n}h", pcm16_mono[: n * 2])
    acc = sum(s * s for s in samples)
    return (acc / n) ** 0.5


class EnergyVAD:
    """Simple energy-based VAD used by the minimal pipeline / tests."""

    def __init__(self, threshold: int = 500) -> None:
        self._threshold = threshold

    def is_speech(self, pcm16_mono: bytes) -> bool:
        if not pcm16_mono:
            return False
        return _pcm16_rms(pcm16_mono) >= self._threshold


def try_silero_vad() -> VADAnalyzer | None:
    """Return a Silero analyzer if pipecat is installed, else None."""
    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer  # type: ignore

        logger.info("Silero VAD available via pipecat")
        return SileroVADAnalyzer()  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        logger.debug("Silero VAD not available — using EnergyVAD fallback")
        return None
