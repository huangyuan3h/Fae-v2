"""Voice / text pipeline package.

Layouts:
  - Text smoke: `TextPipelineBot` (LLM → SentenceAggregator → TTS stub)
  - Daily WebRTC: `daily_bot.run_daily_bot` (Silero + SmartTurn + STT/LLM/TTS)
  - Phase 2: inject `LettaMemoryService` upstream of the LLM on both paths
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
