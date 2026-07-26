from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from fae.tool_audit import ToolAuditEvent, ToolAuditStore

router = APIRouter(prefix="/api/tool-audit", tags=["tool-audit"])


class ToolAuditOut(BaseModel):
    id: str
    call_id: str
    session_id: str
    channel: str
    channel_id: str | None
    tool_name: str
    phase: str
    arguments: str
    result: str
    ok: bool | None
    error_code: str | None
    approval_status: str
    started_at: float
    finished_at: float | None
    duration_ms: float | None


def _to_output(event: ToolAuditEvent) -> ToolAuditOut:
    return ToolAuditOut.model_validate(asdict(event))


@router.get("", response_model=list[ToolAuditOut])
async def list_tool_audit(
    request: Request,
    session_id: Annotated[str | None, Query()] = None,
    tool_name: Annotated[str | None, Query()] = None,
    channel: Annotated[str | None, Query()] = None,
    phase: Annotated[str | None, Query()] = None,
    before: Annotated[float | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ToolAuditOut]:
    store = request.app.state.tool_audit
    if not isinstance(store, ToolAuditStore) or store.closed:
        return []
    events = await asyncio.to_thread(
        store.list_events,
        session_id=session_id,
        tool_name=tool_name,
        channel=channel,
        phase=phase,
        before=before,
        limit=limit,
    )
    return [_to_output(event) for event in events]
