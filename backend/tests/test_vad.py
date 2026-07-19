"""Tests for EnergyVAD and Silero availability."""

from __future__ import annotations

import struct

from fae.pipecat.vad import EnergyVAD, default_vad, try_silero_vad


def _pcm(amplitude: int, frames: int = 160) -> bytes:
    return struct.pack(f"<{frames}h", *([amplitude] * frames))


def test_energy_vad_detects_loud_frame() -> None:
    vad = EnergyVAD(threshold=500)
    assert vad.is_speech(_pcm(0)) is False
    assert vad.is_speech(_pcm(2000)) is True


def test_try_silero_available_with_pipecat() -> None:
    result = try_silero_vad()
    assert result is not None


def test_default_vad_prefers_silero() -> None:
    vad = default_vad()
    assert vad is not None
