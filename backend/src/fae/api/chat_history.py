from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from fae.chat_history import ChatHistoryStore

logger = logging.getLogger("fae.api.chat_history")

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatHistoryTurnOut(BaseModel):
    id: str
    session_id: str
    user_text: str
    assistant_text: str
    created_at: str


class ChatHistoryOut(BaseModel):
    session_id: str
    retention_days: int
    turns: list[ChatHistoryTurnOut]
    has_more: bool


class ChatSessionSummary(BaseModel):
    session_id: str
    title: str
    pinned: bool
    turn_count: int
    last_activity_at: str


class ChatSessionsOut(BaseModel):
    retention_days: int
    sessions: list[ChatSessionSummary]


class ChatSessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatSessionPinPatch(BaseModel):
    pinned: bool


def _to_turn_out(turn) -> ChatHistoryTurnOut:
    return ChatHistoryTurnOut(
        id=turn.id,
        session_id=turn.session_id,
        user_text=turn.user_text,
        assistant_text=turn.assistant_text,
        created_at=turn.created_at.isoformat(),
    )


@router.get("/sessions", response_model=ChatSessionsOut)
async def list_chat_sessions(request: Request) -> ChatSessionsOut:
    store = getattr(request.app.state, "chat_history", None)
    if not isinstance(store, ChatHistoryStore) or store.closed:
        raise HTTPException(status_code=503, detail="chat history unavailable")
    rows = await asyncio.to_thread(store.list_sessions)
    return ChatSessionsOut(
        retention_days=store.retention_days,
        sessions=[
            ChatSessionSummary(
                session_id=str(row["session_id"]),
                title=str(row.get("title", "") or ""),
                pinned=bool(row.get("pinned", False)),
                turn_count=int(row["turn_count"]),  # type: ignore[arg-type]
                last_activity_at=str(row["last_activity_at"]),
            )
            for row in rows
        ],
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionSummary)
async def patch_chat_session(
    session_id: str,
    payload: ChatSessionPatch,
    request: Request,
) -> ChatSessionSummary:
    store = getattr(request.app.state, "chat_history", None)
    if not isinstance(store, ChatHistoryStore) or store.closed:
        raise HTTPException(status_code=503, detail="chat history unavailable")
    sid = (session_id or "").strip() or "default"
    if payload.title is None:
        raise HTTPException(status_code=400, detail="no fields to update")
    store.ensure_session(sid)
    if not await asyncio.to_thread(store.update_session_title, sid, payload.title):
        raise HTTPException(status_code=404, detail="session not found")
    rows = await asyncio.to_thread(store.list_sessions)
    for row in rows:
        if row["session_id"] == sid:
            return ChatSessionSummary(
                session_id=sid,
                title=str(row.get("title", "") or ""),
                pinned=bool(row.get("pinned", False)),
                turn_count=int(row["turn_count"]),  # type: ignore[arg-type]
                last_activity_at=str(row["last_activity_at"]),
            )
    raise HTTPException(status_code=404, detail="session not found")


@router.post("/sessions/{session_id}/pin", response_model=ChatSessionSummary)
async def set_pin(
    session_id: str,
    payload: ChatSessionPinPatch,
    request: Request,
) -> ChatSessionSummary:
    store = getattr(request.app.state, "chat_history", None)
    if not isinstance(store, ChatHistoryStore) or store.closed:
        raise HTTPException(status_code=503, detail="chat history unavailable")
    sid = (session_id or "").strip() or "default"
    store.ensure_session(sid)
    if not await asyncio.to_thread(store.set_session_pinned, sid, payload.pinned):
        raise HTTPException(status_code=404, detail="session not found")
    rows = await asyncio.to_thread(store.list_sessions)
    for row in rows:
        if row["session_id"] == sid:
            return ChatSessionSummary(
                session_id=sid,
                title=str(row.get("title", "") or ""),
                pinned=bool(row.get("pinned", False)),
                turn_count=int(row["turn_count"]),  # type: ignore[arg-type]
                last_activity_at=str(row["last_activity_at"]),
            )
    raise HTTPException(status_code=404, detail="session not found")


@router.get("/history", response_model=ChatHistoryOut)
async def get_chat_history(
    request: Request,
    session_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    before: str | None = Query(default=None, max_length=64),
) -> ChatHistoryOut:
    store = getattr(request.app.state, "chat_history", None)
    if not isinstance(store, ChatHistoryStore) or store.closed:
        raise HTTPException(status_code=503, detail="chat history unavailable")
    sid = session_id.strip() or "default"
    try:
        turns, has_more = await asyncio.to_thread(
            store.list_with_more, sid, limit=limit, before=before,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ChatHistoryOut(
        session_id=sid,
        retention_days=store.retention_days,
        turns=[_to_turn_out(t) for t in turns],
        has_more=has_more,
    )


async def persist_chat_history_turn(
    app: object,
    *,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    state = getattr(app, "state", None)
    store = getattr(state, "chat_history", None)
    if not isinstance(store, ChatHistoryStore) or store.closed or not user_text:
        return
    try:
        await asyncio.to_thread(
            store.append,
            session_id,
            user_text,
            assistant_text,
        )
    except Exception:
        logger.exception("Failed to persist chat history turn")
