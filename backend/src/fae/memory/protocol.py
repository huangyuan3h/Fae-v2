"""Shared memory client protocol (remote Letta + embedded SQLite)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fae.memory.schemas import FactIn, FactOut, RecallTurn, UserProfile


@runtime_checkable
class MemoryClient(Protocol):
    agent_name: str

    @property
    def agent_id(self) -> str | None: ...

    async def ensure_agent(self) -> str: ...

    async def save_fact(self, fact: FactIn) -> FactOut: ...

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]: ...

    async def list_facts(self, *, limit: int = 50, query: str | None = None) -> list[FactOut]: ...

    async def update_fact(self, fact_id: str, fact: FactIn) -> FactOut: ...

    async def delete_fact(self, fact_id: str) -> bool: ...

    async def update_user(self, profile: UserProfile) -> UserProfile: ...

    async def get_block(self, label: str) -> str: ...

    async def set_block(self, label: str, value: str) -> None: ...

    async def append_recall(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None: ...

    async def list_recall(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[RecallTurn]: ...

    async def recall_for_prompt(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
        recent_limit: int = 10,
    ) -> str: ...

    async def close(self) -> None: ...
