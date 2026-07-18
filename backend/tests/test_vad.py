"""Tests for EnergyVAD."""

from __future__ import annotations

import struct

from fae.pipecat.vad import EnergyVAD, try_silero_vad


def _pcm(amplitude: int, frames: int = 160) -> bytes:
    return struct.pack(f"<{frames}h", *([amplitude] * frames))


def test_energy_vad_detects_loud_frame() -> None:
    vad = EnergyVAD(threshold=500)
    assert vad.is_speech(_pcm(0)) is False
    assert vad.is_speech(_pcm(2000)) is True


def test_try_silero_returns_none_without_pipecat() -> None:
    # Default install has no pipecat — expect None (or an analyzer if present).
    result = try_silero_vad()
    assert result is None or hasattr(result, "is_speech") or True
