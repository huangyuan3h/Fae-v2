"""WebSocket connection hub for proactive notification broadcast."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger("fae.scheduler.hub")


class ConnectionHub:
    """Track active /ws/chat connections for server-push notifications."""

    def __init__(self) -> None:
        self._by_ws: dict[int, tuple[WebSocket, str]] = {}

    def register(self, ws: WebSocket, session_id: str = "") -> None:
        self._by_ws[id(ws)] = (ws, session_id or "")

    def update_session(self, ws: WebSocket, session_id: str) -> None:
        key = id(ws)
        if key in self._by_ws:
            self._by_ws[key] = (ws, session_id or "")

    def unregister(self, ws: WebSocket) -> None:
        self._by_ws.pop(id(ws), None)

    def active_count(self) -> int:
        return len(self._by_ws)

    def sessions(self) -> list[str]:
        return sorted({sid for _, sid in self._by_ws.values() if sid})

    async def broadcast(
        self,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> int:
        """Send JSON to connected clients. Returns number of successful sends."""
        sent = 0
        dead: list[int] = []
        for key, (ws, sid) in list(self._by_ws.items()):
            if session_id and sid and sid != session_id:
                continue
            if ws.client_state != WebSocketState.CONNECTED:
                dead.append(key)
                continue
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:  # noqa: BLE001
                logger.debug("hub broadcast failed", exc_info=True)
                dead.append(key)
        for key in dead:
            self._by_ws.pop(key, None)
        return sent
