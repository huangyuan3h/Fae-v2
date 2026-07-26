"""WebSocket endpoints for streaming chat.

Protocol (JSON over text frames):

  client -> server:
    {"type": "chat",  "request": <ChatRequest>, "session_id": "<optional>"}
    {"type": "cancel"}

  server -> client:
    {"type": "skills", "active": ["technical_debugging"], "lazy_catalog": [...]}
    {"type": "subagent", "phase": "start"|"done", "name": "researcher", ...}
    {"type": "token", "content": "你"}
    {"type": "done",  "usage": {...} | null, "session_id": "..."}
    {"type": "notification", "id": "...", "title": "...", "body": "..."}
    {"type": "error", "code": "auth", "message": "..."}

Only one active generation per connection. A new `chat` message cancels
the in-flight one before starting.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from fae.agent.llm_turn import stream_assistant_turn
from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_runtime import SkillRuntime
from fae.api.auth import ensure_ws_client_token
from fae.api.chat_history import persist_chat_history_turn
from fae.api.deps import get_llm_client
from fae.channels.bridge import MissingServerLLMError, merge_chat_request
from fae.llm import ChatRequest, LLMClient, LLMError
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.scheduler.activity import ActivityTracker
from fae.scheduler.hub import ConnectionHub

logger = logging.getLogger("fae.ws")

router = APIRouter()


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    """Send a JSON message, ignoring the rare client-gone-mid-send case."""
    if ws.client_state != WebSocketState.CONNECTED:
        return
    try:
        await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        pass


async def _cancel_active(active: asyncio.Task[None] | None) -> None:
    """Cancel an in-flight stream task and wait for it to finish cleanup."""
    if active is None or active.done():
        return
    active.cancel()
    try:
        await active
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass


def _memory_from_app(ws: WebSocket) -> LettaMemoryService | None:
    memory = getattr(ws.app.state, "memory", None)
    return memory if isinstance(memory, LettaMemoryService) else None


def _skills_from_app(ws: WebSocket) -> SkillRuntime | None:
    skills = getattr(ws.app.state, "skills", None)
    return skills if isinstance(skills, SkillRuntime) else None


def _resolve_session_id(
    raw: dict[str, Any],
    request: ChatRequest,
    connection_session_id: str,
) -> str:
    for candidate in (
        raw.get("session_id"),
        request.session_id,
        connection_session_id,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return connection_session_id


async def _run_stream(
    ws: WebSocket,
    client: LLMClient,
    request: ChatRequest,
    memory: LettaMemoryService | None,
    skills: SkillRuntime | None,
    session_id: str,
    cancel_event: asyncio.Event | None = None,
) -> None:
    """Pump tokens from the provider to the client until done or cancelled."""
    user_text = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_text = msg.content
            break

    try:
        settings = getattr(ws.app.state, "settings", None)
        stream_request, activation, default_city = await prepare_chat_request(
            request,
            session_id=session_id,
            memory=memory,
            skills=skills,
            default_city=getattr(settings, "weather_default_city", "") or "",
            default_timezone=getattr(settings, "weather_default_timezone", "") or "",
        )
        await _send(
            ws,
            {
                "type": "skills",
                "active": activation.active,
                "lazy_catalog": activation.lazy_catalog,
                "scores": activation.scores,
            },
        )

        assistant_parts: list[str] = []
        last_active = list(activation.active)
        schedule_store = getattr(ws.app.state, "schedule_store", None)
        if not getattr(settings, "scheduler_enabled", False):
            schedule_store = None
        proactive = getattr(ws.app.state, "proactive", None)
        from fae.tools.weather import weather_likely

        weather_on = bool(getattr(settings, "weather_enabled", True)) and (
            weather_likely(user_text) or "weather_briefing" in activation.active
        )
        subagent_on = bool(getattr(settings, "subagent_enabled", True))
        subagent_timeout = float(
            getattr(settings, "subagent_timeout_s", 60.0) or 60.0
        )
        coding_root = str(getattr(settings, "coding_workspace_root", "") or "").strip()
        filesystem_on = bool(coding_root and getattr(settings, "coding_filesystem_enabled", False))
        bash_on = bool(coding_root and getattr(settings, "coding_bash_enabled", False))
        git_on = bool(coding_root and getattr(settings, "coding_git_enabled", False))
        if cancel_event is None:
            cancel_event = asyncio.Event()

        def _on_sched_mut() -> None:
            if proactive is not None and hasattr(proactive, "resync"):
                proactive.resync()

        async def _on_subagent(ev: dict) -> None:
            await _send(ws, ev)

        async def _on_tool(ev: dict) -> None:
            await _send(ws, ev)

        async for token, activation in stream_assistant_turn(
            client,
            stream_request,
            activation,
            skills,
            session_id=session_id,
            schedule_store=schedule_store,
            weather_enabled=weather_on,
            default_city=default_city,
            on_schedule_mutated=_on_sched_mut,
            memory=memory,
            subagent_enabled=subagent_on,
            subagent_timeout_s=subagent_timeout,
            workspace_root=coding_root,
            filesystem_enabled=filesystem_on,
            bash_enabled=bash_on,
            bash_timeout_s=float(getattr(settings, "coding_bash_timeout_s", 30.0)),
            git_enabled=git_on,
            git_timeout_s=float(getattr(settings, "coding_git_timeout_s", 20.0)),
            cancel_event=cancel_event,
            on_subagent_event=_on_subagent,
            on_tool_event=_on_tool,
            tool_offloader=getattr(ws.app.state, "tool_offloader", None),
        ):
            if activation.active != last_active:
                last_active = list(activation.active)
                await _send(
                    ws,
                    {
                        "type": "skills",
                        "active": activation.active,
                        "lazy_catalog": activation.lazy_catalog,
                        "scores": activation.scores,
                    },
                )
            assistant_parts.append(token)
            await _send(ws, {"type": "token", "content": token})
        assistant_text = "".join(assistant_parts)
        stream_usage = getattr(client, "last_stream_usage", None)
        usage_payload: dict[str, int] | None = None
        if stream_usage is not None:
            usage_payload = stream_usage.model_dump(exclude_none=True)
        await persist_chat_history_turn(
            ws.app,
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
        )
        if memory is not None and memory.enabled and user_text:
            await memory.persist_turn(
                session_id=session_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        else:
            activity = getattr(ws.app.state, "activity", None)
            if isinstance(activity, ActivityTracker):
                activity.touch(session_id)
        await _send(
            ws,
            {
                "type": "done",
                "usage": usage_payload,
                "session_id": session_id,
                "active_skills": last_active,
            },
        )
    except LLMError as e:
        await _send(ws, {"type": "error", "code": e.code, "message": e.message})
    except asyncio.CancelledError:
        await _send(
            ws, {"type": "done", "usage": None, "session_id": session_id}
        )
        raise
    except Exception as e:  # noqa: BLE001 — last-resort
        logger.exception("Unexpected stream error")
        await _send(
            ws, {"type": "error", "code": "unknown", "message": f"{e}"}
        )


@router.websocket("/ws/chat")
async def ws_chat(
    websocket: WebSocket,
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> None:
    """Streaming chat over WebSocket."""
    if not await ensure_ws_client_token(websocket):
        return
    await websocket.accept()
    active: asyncio.Task[None] | None = None
    stream_cancel: asyncio.Event | None = None
    # Fallback when client omits session_id; UI should send stable "default".
    connection_session_id = "default"
    hub = getattr(websocket.app.state, "ws_hub", None)
    if isinstance(hub, ConnectionHub):
        hub.register(websocket, connection_session_id)
    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as e:  # noqa: BLE001 — malformed frame
                await _send(
                    websocket,
                    {
                        "type": "error",
                        "code": "bad_request",
                        "message": f"Invalid JSON frame: {e}",
                    },
                )
                continue

            if not isinstance(raw, dict):
                await _send(
                    websocket,
                    {
                        "type": "error",
                        "code": "bad_request",
                        "message": "Frame must be a JSON object",
                    },
                )
                continue

            msg_type = raw.get("type")

            if msg_type == "cancel":
                if stream_cancel is not None:
                    stream_cancel.set()
                await _cancel_active(active)
                active = None
                stream_cancel = None
                continue

            if msg_type == "chat":
                if stream_cancel is not None:
                    stream_cancel.set()
                await _cancel_active(active)
                active = None
                stream_cancel = None

                try:
                    request = ChatRequest.model_validate(raw.get("request", {}))
                except ValidationError as e:
                    await _send(
                        websocket,
                        {
                            "type": "error",
                            "code": "bad_request",
                            "message": (
                                f"Invalid ChatRequest: {e.errors()[0]['msg']}"
                            ),
                        },
                    )
                    continue

                settings = getattr(websocket.app.state, "settings", None)
                if settings is not None:
                    try:
                        request = merge_chat_request(request, settings)
                    except MissingServerLLMError as e:
                        await _send(
                            websocket,
                            {
                                "type": "error",
                                "code": "no_llm",
                                "message": e.message,
                            },
                        )
                        continue

                session_id = _resolve_session_id(
                    raw, request, connection_session_id
                )
                if isinstance(hub, ConnectionHub):
                    hub.update_session(websocket, session_id)
                memory = _memory_from_app(websocket)
                skills = _skills_from_app(websocket)
                stream_cancel = asyncio.Event()
                active = asyncio.create_task(
                    _run_stream(
                        websocket,
                        client,
                        request,
                        memory,
                        skills,
                        session_id,
                        cancel_event=stream_cancel,
                    )
                )
                continue

            await _send(
                websocket,
                {
                    "type": "error",
                    "code": "bad_request",
                    "message": f"Unknown message type: {msg_type!r}",
                },
            )
    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    finally:
        if isinstance(hub, ConnectionHub):
            hub.unregister(websocket)
        await _cancel_active(active)
