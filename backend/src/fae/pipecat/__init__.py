"""Voice pipeline scaffolding (Phase 1.3 minimal attempt).

This package mirrors the eventual Pipecat layout without pulling the full
`pipecat-ai` dependency yet (heavy Daily/Silero wheels). Components here are
plain async adapters that unit-test cleanly and can later wrap FrameProcessors.

Pipeline shape (text-mode smoke):
  user text → Qwen3LLM → SentenceAggregator → (TTS stub) → events

Voice path (ASR / Daily transport / Silero VAD) is stubbed with clear
interfaces for the next checkpoint.
"""

from fae.pipecat.barge_in import BargeInController
from fae.pipecat.bot import PipelineEvent, TextPipelineBot
from fae.pipecat.sentence import SentenceAggregator
from fae.pipecat.vad import EnergyVAD

__all__ = [
    "BargeInController",
    "EnergyVAD",
    "PipelineEvent",
    "SentenceAggregator",
    "TextPipelineBot",
]
