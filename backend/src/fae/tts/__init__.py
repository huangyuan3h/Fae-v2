"""Text-to-speech helpers (local OpenAI-compatible only)."""

from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.speakable import to_speakable_text
from fae.tts.wav import pcm16_mono_to_wav

__all__ = [
    "LocalTTSClient",
    "LocalTTSError",
    "pcm16_mono_to_wav",
    "to_speakable_text",
]
