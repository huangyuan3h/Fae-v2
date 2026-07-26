"""Data deletion orchestrator for "one-click forget" (session or global)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from fae.agent.tool_offload import ToolOffloader
from fae.agent_trace import AgentTraceStore
from fae.approvals import ApprovalStore
from fae.chat_history import ChatHistoryStore
from fae.memory.archival import ArchivalBackend
from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.episodic import EpisodicStore
from fae.memory.letta_client import LettaMemoryClient
from fae.memory.recall_store import RecallStore
from fae.scheduler.store import ScheduleStore
from fae.scheduler.tasks import TaskStore


@dataclass
class DataDeletionResult:
    session_id: str | None
    global_mode: bool
    counts: Dict[str, int]


class DataDeletionService:
    """Orchestrates deletion across all data stores.

    Supports two modes:
      - Session-scoped: delete only the data for one session.
      - Global: clear all user data (keep system config).
    """

    def __init__(
        self,
        chat_history: ChatHistoryStore,
        tool_audit: ToolAuditStore,
        agent_trace: AgentTraceStore,
        approvals: ApprovalStore,
        task_store: TaskStore,
        schedule_store: ScheduleStore,
        recall_store: RecallStore,
        episodic_store: EpisodicStore,
        embedded_memory: EmbeddedMemoryClient | None,
        letta_memory: LettaMemoryClient | None,
        archival: ArchivalBackend,
        tool_offloader: ToolOffloader | None,
    ):
        self.chat_history = chat_history
        self.tool_audit = tool_audit
        self.agent_trace = agent_trace
        self.approvals = approvals
        self.task_store = task_store
        self.schedule_store = schedule_store
        self.recall_store = recall_store
        self.episodic_store = episodic_store
        self.embedded_memory = embedded_memory
        self.letta_memory = letta_memory
        self.archival = archival
        self.tool_offloader = tool_offloader

    async def forget(self, session_id: str | None = None) -> DataDeletionResult:
        """Clear user data for one session or everything.

        Args:
            session_id: If None, delete globally. If provided, delete only
                        this session's scoped data (retention of system config).
        """
        global_mode = session_id is None
        counts: Dict[str, int] = {}

        # 1. Scoped SQLite stores (session_id column exists)
        if global_mode:
            counts["chat_history"] = await self._delete(
                self.chat_history.clear, session_id=None
            )
            counts["tool_audit"] = await self._delete(
                self.tool_audit.clear, session_id=None
            )
            counts["agent_trace"] = await self._delete(
                self.agent_trace.clear, session_id=None
            )
            counts["approvals"] = await self._delete(
                self.approvals.clear, session_id=None
            )
            counts["tasks"] = await self._delete(
                self.task_store.clear, session_id=None
            )
        else:
            counts["chat_history"] = await self._delete(
                self.chat_history.clear, session_id=session_id
            )
            counts["tool_audit"] = await self._delete(
                self.tool_audit.clear, session_id=session_id
            )
            counts["agent_trace"] = await self._delete(
                self.agent_trace.clear, session_id=session_id
            )
            counts["approvals"] = await self._delete(
                self.approvals.clear, session_id=session_id
            )
            counts["tasks"] = await self._delete(
                self.task_store.clear, session_id=session_id
            )

        # 2. Schedule store (keep builtin jobs, clear user data)
        counts["schedules"] = await self._delete(
            self.schedule_store.clear_user, session_id=session_id
        )

        # 3. Recall store (hot)
        counts["recall_hot"] = await self._delete(
            self.recall_store.clear, session_id=session_id
        )

        # 4. Episodic store
        counts["episodic"] = await self._delete(
            self.episodic_store.clear, session_id=session_id
        )

        # 5. Embedded memory facts
        if global_mode:
            if self.embedded_memory is not None:
                counts["embedded_facts"] = await self._delete(
                    self.embedded_memory.delete_all_facts
                )
        else:
            if self.embedded_memory is not None:
                counts["embedded_facts"] = await self._delete(
                    self.embedded_memory.delete_session_facts, session_id=session_id
                )

        # 6. Letta memory facts (remote)
        if global_mode:
            if self.letta_memory is not None:
                counts["letta_facts"] = await self._delete(
                    self.letta_memory.delete_all_facts
                )
        else:
            if self.letta_memory is not None:
                counts["letta_facts"] = await self._delete(
                    self.letta_memory.delete_session_facts, session_id=session_id
                )

        # 7. Archival (vector)
        counts["archival"] = await self._delete(
            self.archival.clear, session_id=session_id
        )

        # 8. Tool offload
        if self.tool_offloader:
            counts["tool_offload"] = await self._delete(
                self.tool_offloader.clear, session_id=session_id
            )

        return DataDeletionResult(
            session_id=session_id,
            global_mode=global_mode,
            counts=counts,
        )

    async def _delete(
        self, fn: Any, *, session_id: str | None = None
    ) -> int:
        """Run a store's clear/delete method, returning count or 0."""
        try:
            if session_id is not None:
                result = fn(session_id=session_id)
            else:
                result = fn()
            if asyncio.iscoroutine(result):
                return await result
            return int(result or 0)
        except Exception:
            return 0