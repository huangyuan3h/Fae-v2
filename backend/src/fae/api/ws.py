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
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from fae.llm import ChatRequest, LLMClient, LLMError

logger = logging.getLogger("fae.ws")

router = APIRouter()


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    """Send a JSON message, ignoring the rare client-gone-mid-send case."""
    try:
        await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        # Client already gone — nothing to do. The cancellation will
        # propagate through the stream task and clean up the provider.
        pass


async def _run_stream(
    ws: WebSocket, client: LLMClient, request: ChatRequest
) -> None:
    """Pump tokens from the provider to the client until done or cancelled."""
    try:
        async for token in client.stream(request):
            await _send(ws, {"type": "token", "content": token})
        await _send(ws, {"type": "done", "usage": None})
    except LLMError as e:
        await _send(ws, {"type": "error", "code": e.code, "message": e.message})
    except asyncio.CancelledError:
        # Client sent `cancel` or disconnected. Let the wrapper send
        # a `done` so the UI doesn't hang in "thinking...".
        await _send(ws, {"type": "done", "usage": None})
        raise
    except Exception as e:  # noqa: BLE001 — last-resort
        logger.exception("Unexpected stream error")
        await _send(
            ws, {"type": "error", "code": "unknown", "message": f"{e}"}
        )


def get_llm_client() -> LLMClient:  # type: ignore[no-redef]
    """Placeholder — overridden in fae.api.__init__.create_app via
    dependency_overrides. Kept as a module-level symbol so the override
    key is stable across reloads and tests.
    """
    raise RuntimeError(
        "get_llm_client must be overridden via app.dependency_overrides"
    )


@router.websocket("/ws/chat")
async def ws_chat(
    websocket: WebSocket,
    client: LLMClient = Depends(get_llm_client),
) -> None:
    """Streaming chat over WebSocket.

    Connection lifecycle:
      1. Client connects.
      2. Client sends `{"type":"chat", "request": ChatRequest}`.
      3. Server streams `token` messages.
      4. Server sends `done` (or `error` on failure).
      5. Client may send another `chat` or `cancel` (cancels in-flight stream).
      6. Client closes the connection.
    """
    await websocket.accept()
    active: asyncio.Task[None] | None = None
    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "cancel":
                if active is not None and not active.done():
                    active.cancel()
                continue

            if msg_type == "chat":
                # Cancel any in-flight stream — one generation per connection.
                if active is not None and not active.done():
                    active.cancel()
                    try:
                        await active
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass

                # Parse and validate the request.
                try:
                    request = ChatRequest.model_validate(raw.get("request", {}))
                except ValidationError as e:
                    await _send(
                        websocket,
                        {
                            "type": "error",
                            "code": "bad_request",
                            "message": f"Invalid ChatRequest: {e.errors()[0]['msg']}",
                        },
                    )
                    continue

                active = asyncio.create_task(_run_stream(websocket, client, request))
                continue

            # Unknown message type — be lenient, don't disconnect.
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
        if active is not None and not active.done():
            active.cancel()
            try:
                await active
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
