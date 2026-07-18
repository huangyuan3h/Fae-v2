"""Voice session bootstrap — browser Web Speech or Daily / Pipecat."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from fae.sessions import SessionStore

logger = logging.getLogger("fae.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceSessionRequest(BaseModel):
    prefer_daily: bool = False
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None


class VoiceSessionOut(BaseModel):
    mode: Literal["browser", "daily"]
    sessionId: str
    roomUrl: str | None = None
    token: str | None = None
    detail: str | None = None


def _sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


async def _launch_daily_bot(
    room_url: str,
    token: str,
    request: Request,
    body: VoiceSessionRequest,
) -> None:
    from fae.pipecat.daily_bot import run_daily_bot

    settings = request.app.state.settings
    try:
        await run_daily_bot(
            room_url=room_url,
            token=token,
            settings=settings,
            llm_api_key=body.llm_api_key,
            llm_base_url=body.llm_base_url,
            llm_model=body.llm_model,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Daily bot crashed")


@router.post("/session", response_model=VoiceSessionOut)
async def create_voice_session(
    body: VoiceSessionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    store: Annotated[SessionStore, Depends(_sessions)],
) -> VoiceSessionOut:
    settings = request.app.state.settings
    session = store.create(mode="voice")
    daily_key = (settings.daily_api_key or "").strip()

    if body.prefer_daily and daily_key:
        try:
            from fae.pipecat.daily_rooms import create_daily_room

            room = await create_daily_room(daily_key)
        except Exception as e:  # noqa: BLE001
            logger.exception("Daily room creation failed")
            raise HTTPException(
                status_code=502,
                detail={"code": "daily", "message": str(e)},
            ) from e

        background_tasks.add_task(
            _launch_daily_bot, room.room_url, room.token, request, body
        )
        # Give the bot a moment to subscribe before the client joins.
        await asyncio.sleep(0.3)
        return VoiceSessionOut(
            mode="daily",
            sessionId=session.id,
            roomUrl=room.room_url,
            token=room.token,
            detail="Pipecat Daily bot started",
        )

    detail = "browser Web Speech path"
    if body.prefer_daily and not daily_key:
        detail = "DAILY_API_KEY not set — falling back to browser mode"

    return VoiceSessionOut(
        mode="browser",
        sessionId=session.id,
        detail=detail,
    )


class BargeInBody(BaseModel):
    session_id: str = Field(min_length=1)


@router.post("/barge-in")
async def barge_in_hook(body: BargeInBody) -> dict[str, str]:
    """Explicit barge-in signal for clients that don't own the WS cancel path."""
    return {"status": "ok", "session_id": body.session_id, "action": "interrupted"}
