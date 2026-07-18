"""Shared memory client protocol (remote Letta + embedded SQLite)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fae.memory.schemas import FactIn, FactOut, UserProfile


@runtime_checkable
class MemoryClient(Protocol):
    agent_name: str

    @property
    def agent_id(self) -> str | None: ...

    async def ensure_agent(self) -> str: ...

    async def save_fact(self, fact: FactIn) -> FactOut: ...

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]: ...

    async def update_user(self, profile: UserProfile) -> UserProfile: ...

    async def recall_for_prompt(self, query: str, *, top_k: int = 10) -> str: ...

    async def close(self) -> None: ...
