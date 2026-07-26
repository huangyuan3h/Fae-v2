"""Queryable Agent execution trace API.

GET /api/agent-trace — filtered, time-ordered (descending) view of the
events that ``stream_assistant_turn`` produced for a session. ``turn_id``
filters to a single turn's sequence when supplied. Results are capped
(default 200; hard cap 500) and ``before`` (epoch seconds) supports
cursor pagination.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from fae.agent_trace import AgentTraceEvent, AgentTraceStore

router = APIRouter(prefix="/api/agent-trace", tags=["agent-trace"])


class AgentTraceEventOut(BaseModel):
    id: int
    turn_id: str
    session_id: str
    channel: str
    channel_id: str | None
    kind: str
    phase: str
    name: str
    payload: str
    started_at: float
    finished_at: float | None
    duration_ms: float | None
    ok: bool | None
    error_code: str | None


def _to_output(event: AgentTraceEvent) -> AgentTraceEventOut:
    return AgentTraceEventOut.model_validate(asdict(event))


@router.get("", response_model=list[AgentTraceEventOut])
async def list_agent_trace(
    request: Request,
    session_id: Annotated[str | None, Query()] = None,
    turn_id: Annotated[str | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    before: Annotated[float | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[AgentTraceEventOut]:
    store = getattr(request.app.state, "agent_trace", None)
    if not isinstance(store, AgentTraceStore) or store.closed:
        return []
    events = await asyncio.to_thread(
        store.list_events,
        session_id=session_id,
        turn_id=turn_id,
        kind=kind,
        before=before,
        limit=limit,
    )
    return [_to_output(event) for event in events]
