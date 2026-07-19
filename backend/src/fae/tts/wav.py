"""Wrap raw PCM16 LE mono into a WAV container for browser <audio>."""

from __future__ import annotations

import struct


def pcm16_mono_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    """Return a minimal RIFF/WAVE blob for 16-bit mono PCM."""
    if not pcm:
        return b""
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # PCM fmt chunk size
        1,  # audio format = PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm
