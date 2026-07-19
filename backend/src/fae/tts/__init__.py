"""Text-to-speech helpers (Qwen3-TTS via DashScope)."""

from fae.tts.speakable import to_speakable_text
from fae.tts.wav import pcm16_mono_to_wav

__all__ = ["pcm16_mono_to_wav", "to_speakable_text"]
