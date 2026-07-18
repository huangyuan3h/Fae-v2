"""WebSocket endpoints for streaming chat.

Protocol (JSON over text frames):

  client -> server:
    {"type": "chat",  "request": <ChatRequest>}
    {"type": "cancel"}

  server -> client:
    {"type": "token", "content": "你"}
    {"type": "done",  "usage": {...} | null}
    {"type": "error", "code": "auth", "message": "..."}

Only one active generation per connection. A new `chat` message cancels
the in-flight one before starting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

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


async def _run_stream(
    ws: WebSocket,
    client: LLMClient,
    request: ChatRequest,
    memory: LettaMemoryService | None,
) -> None:
    """Pump tokens from the provider to the client until done or cancelled."""
    user_text = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_text = msg.content
            break

    stream_request = request
    if memory is not None and memory.enabled:
        stream_request = await memory.prepare_request(request, session_id="ws")

    assistant_parts: list[str] = []
    try:
        async for token in client.stream(stream_request):
            assistant_parts.append(token)
            await _send(ws, {"type": "token", "content": token})
        if memory is not None and memory.enabled and user_text:
            await memory.persist_turn(
                session_id="ws",
                user_text=user_text,
                assistant_text="".join(assistant_parts),
            )
        await _send(ws, {"type": "done", "usage": None})
    except LLMError as e:
        await _send(ws, {"type": "error", "code": e.code, "message": e.message})
    except asyncio.CancelledError:
        await _send(ws, {"type": "done", "usage": None})
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

                memory = _memory_from_app(websocket)
                active = asyncio.create_task(
                    _run_stream(websocket, client, request, memory)
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
