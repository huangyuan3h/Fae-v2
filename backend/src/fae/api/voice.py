"""Voice session bootstrap — browser Web Speech or Daily / Pipecat."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from fae.sessions import SessionStore
from fae.voice_runtime import VoiceRuntime

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


def _runtime(request: Request) -> VoiceRuntime:
    return request.app.state.voice_runtime


@router.post("/session", response_model=VoiceSessionOut)
async def create_voice_session(
    body: VoiceSessionRequest,
    request: Request,
    store: Annotated[SessionStore, Depends(_sessions)],
    runtime: Annotated[VoiceRuntime, Depends(_runtime)],
) -> VoiceSessionOut:
    settings = request.app.state.settings
    session = store.create(mode="voice")
    handle = runtime.register(session.id)
    daily_key = (settings.daily_api_key or "").strip()

    if body.prefer_daily and daily_key:
        try:
            from fae.pipecat.daily_bot import run_daily_bot
            from fae.pipecat.daily_rooms import create_daily_room

            room = await create_daily_room(daily_key)
        except Exception as e:  # noqa: BLE001
            logger.exception("Daily room creation failed")
            raise HTTPException(
                status_code=502,
                detail={"code": "daily", "message": str(e)},
            ) from e

        handle.room_url = room.room_url
        session.meta["room_url"] = room.room_url
        session.meta["transport"] = "daily"

        def _bind_interrupt(interrupt_fn):  # noqa: ANN001
            handle.interrupt_pipeline = interrupt_fn

        runtime.spawn(
            session.id,
            run_daily_bot(
                room_url=room.room_url,
                token=room.token,
                settings=settings,
                llm_api_key=body.llm_api_key,
                llm_base_url=body.llm_base_url,
                llm_model=body.llm_model,
                on_ready=_bind_interrupt,
            ),
        )
        return VoiceSessionOut(
            mode="daily",
            sessionId=session.id,
            roomUrl=room.room_url,
            token=room.token,
            detail="Pipecat Daily bot started",
        )

    session.meta["transport"] = "browser"
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
async def barge_in_hook(
    body: BargeInBody,
    runtime: Annotated[VoiceRuntime, Depends(_runtime)],
) -> dict[str, str]:
    """Explicit barge-in for UI / clients that don't own the WS cancel path."""
    ok = await runtime.interrupt(body.session_id)
    if not ok:
        # Still acknowledge — browser path may only need local cancel + TTS stop.
        return {
            "status": "ok",
            "session_id": body.session_id,
            "action": "interrupted",
            "detail": "no active handle",
        }
    return {"status": "ok", "session_id": body.session_id, "action": "interrupted"}
