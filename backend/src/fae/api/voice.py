"""Voice session bootstrap.

Returns a browser-mode session by default. When DAILY_API_KEY is set,
future revisions can mint a Daily room for the Pipecat WebRTC path.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from fae.sessions import SessionStore

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceSessionOut(BaseModel):
    mode: Literal["browser", "daily"]
    sessionId: str
    roomUrl: str | None = None
    token: str | None = None


def _sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


@router.post("/session", response_model=VoiceSessionOut)
async def create_voice_session(
    request: Request,
    store: Annotated[SessionStore, Depends(_sessions)],
) -> VoiceSessionOut:
    settings = request.app.state.settings
    session = store.create(mode="voice")
    daily_key = getattr(settings, "daily_api_key", "") or ""
    if daily_key:
        # Placeholder for Daily room minting — browser path remains default
        # until the Pipecat Daily bot is wired end-to-end.
        return VoiceSessionOut(
            mode="browser",
            sessionId=session.id,
            roomUrl=None,
            token=None,
        )
    return VoiceSessionOut(mode="browser", sessionId=session.id)
