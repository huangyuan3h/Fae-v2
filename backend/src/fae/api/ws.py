"""WebSocket endpoints for streaming chat.

Protocol (JSON over text frames):

  client -> server:
    {"type": "chat",  "request": <ChatRequest>, "session_id": "<optional>"}
    {"type": "cancel"}

  server -> client:
    {"type": "skills", "active": ["technical_debugging"], "lazy_catalog": [...]}
    {"type": "token", "content": "你"}
    {"type": "done",  "usage": {...} | null, "session_id": "..."}
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
from fae.api.deps import get_llm_client
from fae.llm import ChatRequest, LLMClient, LLMError
from fae.pipecat.services.letta_memory import LettaMemoryService

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
) -> None:
    """Pump tokens from the provider to the client until done or cancelled."""
    user_text = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_text = msg.content
            break

    try:
        stream_request, activation = await prepare_chat_request(
            request,
            session_id=session_id,
            memory=memory,
            skills=skills,
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
        async for token, activation in stream_assistant_turn(
            client, stream_request, activation, skills
        ):
            assistant_parts.append(token)
            await _send(ws, {"type": "token", "content": token})
        if memory is not None and memory.enabled and user_text:
            await memory.persist_turn(
                session_id=session_id,
                user_text=user_text,
                assistant_text="".join(assistant_parts),
            )
        await _send(
            ws, {"type": "done", "usage": None, "session_id": session_id}
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
    await websocket.accept()
    active: asyncio.Task[None] | None = None
    connection_session_id = str(uuid.uuid4())
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
                await _cancel_active(active)
                active = None
                continue

            if msg_type == "chat":
                await _cancel_active(active)
                active = None

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

                session_id = _resolve_session_id(
                    raw, request, connection_session_id
                )
                memory = _memory_from_app(websocket)
                skills = _skills_from_app(websocket)
                active = asyncio.create_task(
                    _run_stream(
                        websocket,
                        client,
                        request,
                        memory,
                        skills,
                        session_id,
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
        await _cancel_active(active)
