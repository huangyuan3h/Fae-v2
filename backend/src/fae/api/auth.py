"""Optional personal client token (FAE_CLIENT_TOKEN)."""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket
from starlette.requests import HTTPConnection

from fae.config import Settings

# Public paths when a client token is configured.
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/ready",
    "/api/capabilities",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def client_token_required(settings: Settings) -> bool:
    return bool((getattr(settings, "fae_client_token", "") or "").strip())


def extract_client_token(conn: HTTPConnection) -> str:
    """Bearer header or access_token query (for browser WebSocket)."""
    auth = (conn.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (conn.query_params.get("access_token") or "").strip()


def token_matches(settings: Settings, provided: str) -> bool:
    expected = (getattr(settings, "fae_client_token", "") or "").strip()
    if not expected:
        return True
    return bool(provided) and provided == expected


def path_is_public(path: str) -> bool:
    if path in PUBLIC_PATH_PREFIXES:
        return True
    for prefix in ("/docs", "/redoc"):
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def require_client_token_http(request: Request) -> None:
    """Raise 401 when FAE_CLIENT_TOKEN is set and request lacks a valid token."""
    settings: Settings = request.app.state.settings
    if not client_token_required(settings):
        return
    if path_is_public(request.url.path):
        return
    if token_matches(settings, extract_client_token(request)):
        return
    raise HTTPException(
        status_code=401,
        detail={"code": "auth", "message": "FAE_CLIENT_TOKEN required"},
    )


async def ensure_ws_client_token(websocket: WebSocket) -> bool:
    """Return False (after close) when WS auth fails."""
    settings: Settings = websocket.app.state.settings
    if not client_token_required(settings):
        return True
    if token_matches(settings, extract_client_token(websocket)):
        return True
    await websocket.close(code=4401)
    return False
