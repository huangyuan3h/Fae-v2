from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel

from fae.data_deletion import DataDeletionService, DataDeletionResult
from fae.approvals import ApprovalStore
from fae.chat_history import ChatHistoryStore
from fae.agent_trace import AgentTraceStore
from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.letta_client import LettaMemoryClient
from fae.memory.archival import ArchivalBackend
from fae.agent.tool_offload import ToolOffloader
from fae.scheduler.store import ScheduleStore
from fae.scheduler.tasks import TaskStore
from fae.sessions import SessionStore

router = APIRouter(
    prefix="/api/data",
    tags=["data"],
)


class ForgetRequest(BaseModel):
    session_id: str | None = None


class ForgetResponse(BaseModel):
    global_mode: bool
    session_id: str | None
    counts: dict[str, int]


@router.post("/forget", response_model=ForgetResponse)
async def forget_data(
    request: Request,
    body: ForgetRequest,
) -> ForgetResponse:
    """Delete user data for a session or globally.

    Requires client token auth. Body: {"session_id": ...?}.
    When session_id is null or omitted, all user data is wiped.
    """
    require_client_token_http(request)

    chat_history: ChatHistoryStore = request.app.state.chat_history
    tool_audit: AgentTraceStore = request.app.state.tool_audit
    agent_trace: AgentTraceStore = request.app.state.agent_trace
    approvals: ApprovalStore = request.app.state.approvals
    task_store: TaskStore = request.app.state.task_store
    schedule_store: ScheduleStore = request.app.state.schedule_store
    recall_store = request.app.state.recall_store
    episodic_store = request.app.state.episodic_store
    embedded_memory: EmbeddedMemoryClient | None = getattr(
        request.app.state, "memory_client", None
    )
    memory_svc = getattr(request.app.state, "memory", None)
    letta_memory: LettaMemoryClient | None = None
    if memory_svc is not None and hasattr(memory_svc, "client"):
        letta_memory = memory_svc.client
    archival: ArchivalBackend | None = request.app.state.archival
    tool_offloader: ToolOffloader | None = getattr(
        request.app.state, "tool_offloader", None
    )
    session_store: SessionStore = request.app.state.sessions

    service = DataDeletionService(
        chat_history=chat_history,
        tool_audit=tool_audit,
        agent_trace=agent_trace,
        approvals=approvals,
        task_store=task_store,
        schedule_store=schedule_store,
        recall_store=recall_store,
        episodic_store=episodic_store,
        embedded_memory=embedded_memory,
        letta_memory=letta_memory,
        archival=archival,
        tool_offloader=tool_offloader,
        session_store=session_store,
    )

    result = await service.forget(session_id=body.session_id)
    return ForgetResponse(
        global_mode=result.global_mode,
        session_id=result.session_id,
        counts=result.counts,
    )