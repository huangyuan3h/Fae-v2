"""Long-term memory layer (Phase 2)."""

from fae.memory.factory import create_memory_client
from fae.memory.schemas import FactIn, FactOut, RecallTurn, UserProfile

__all__ = [
    "FactIn",
    "FactOut",
    "RecallTurn",
    "UserProfile",
    "create_memory_client",
]
