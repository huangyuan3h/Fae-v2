"""Long-term memory layer (Phase 2)."""

from fae.memory.consolidation import ConsolidateResult, MemoryConsolidator, SleeptimeScheduler
from fae.memory.episodic import EpisodicStore, detect_life_events
from fae.memory.factory import MemoryStack, create_memory_client, create_memory_stack
from fae.memory.schemas import (
    EpisodeEvent,
    EpisodeLink,
    FactIn,
    FactOut,
    RecallTurn,
    UserProfile,
)

__all__ = [
    "ConsolidateResult",
    "EpisodeEvent",
    "EpisodeLink",
    "EpisodicStore",
    "FactIn",
    "FactOut",
    "MemoryConsolidator",
    "MemoryStack",
    "RecallTurn",
    "SleeptimeScheduler",
    "UserProfile",
    "create_memory_client",
    "create_memory_stack",
    "detect_life_events",
]
