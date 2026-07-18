"""Shared helpers for memory unit tests."""

from __future__ import annotations

from pathlib import Path

from fae.memory.archival import StubArchival
from fae.memory.compaction import MemoryCompactor
from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.recall_store import RecallStore
from fae.pipecat.services.letta_memory import LettaMemoryService


def make_embedded(
    tmp_path: Path,
    *,
    name: str = "m.db",
    agent_name: str = "fae-main",
    max_turns: int = 30,
    batch: int = 10,
    with_compactor: bool = False,
) -> tuple[EmbeddedMemoryClient, RecallStore, LettaMemoryService]:
    """Build embedded client + shared recall (+ optional stub archival/compactor)."""
    recall = RecallStore(tmp_path / f"{name}.recall.db")
    client = EmbeddedMemoryClient(
        tmp_path / name,
        agent_name=agent_name,
        recall_store=recall,
    )
    archival = StubArchival() if with_compactor else None
    compactor = None
    if with_compactor and archival is not None:
        compactor = MemoryCompactor(
            recall,
            archival,
            max_turns=max_turns,
            batch=batch,
            client=client,
        )
    service = LettaMemoryService(
        client, archival=archival, compactor=compactor
    )
    return client, recall, service
