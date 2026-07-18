"""Long-term memory layer (Phase 2).

Scaffold only — Letta client + schemas land in 2.1; Pipecat injection in 2.2.
Wire `app.state.memory` from `create_app` once LettaMemoryClient is ready.
"""

from fae.memory.schemas import FactIn, FactOut, UserProfile

__all__ = ["FactIn", "FactOut", "UserProfile"]
