"""Wrap / unwrap PCM16 LE mono WAV for browser <audio> and Pipecat."""

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


def wav_to_pcm16_mono(wav: bytes) -> bytes:
    """Extract PCM payload from a simple RIFF/WAVE; pass through non-WAV bytes."""
    if not wav:
        return b""
    if not wav.startswith(b"RIFF") or len(wav) < 12:
        return wav
    offset = 12
    while offset + 8 <= len(wav):
        chunk_id = wav[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", wav, offset + 4)[0]
        data_start = offset + 8
        data_end = data_start + chunk_size
        if chunk_id == b"data":
            return wav[data_start:data_end]
        # RIFF chunks are word-aligned
        offset = data_end + (chunk_size % 2)
    # Fallback: standard 44-byte PCM header
    return wav[44:] if len(wav) > 44 else b""
