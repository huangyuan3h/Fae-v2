"""HTTP surface for the Phase 1.3 text pipeline smoke path."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from fae.api.deps import get_llm_client
from fae.llm import LLMClient, LLMConfig
from fae.pipecat import TextPipelineBot

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    config: LLMConfig
    system_prompt: str | None = None


class PipelineEventOut(BaseModel):
    type: Literal["token", "sentence", "audio", "done", "interrupted", "error"]
    content: str | None = None
    audio_bytes: int | None = None
    meta: dict[str, Any] | None = None


class PipelineTurnResponse(BaseModel):
    events: list[PipelineEventOut]
    sentences: list[str]
    full_text: str


@router.post("/text", response_model=PipelineTurnResponse)
async def pipeline_text_turn(
    body: PipelineTurnRequest,
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> PipelineTurnResponse:
    """Run one text-mode voice-pipeline turn (LLM → sentences → TTS stub).

    This is the Phase 1.3 smoke endpoint — not yet mic/WebRTC.
    """
    bot = TextPipelineBot(client, system_prompt=body.system_prompt)
    events: list[PipelineEventOut] = []
    sentences: list[str] = []
    tokens: list[str] = []

    async for ev in bot.run_turn(body.text, body.config):
        if ev.type == "token" and ev.content:
            tokens.append(ev.content)
        if ev.type == "sentence" and ev.content:
            sentences.append(ev.content)
        events.append(
            PipelineEventOut(
                type=ev.type,
                content=ev.content,
                audio_bytes=len(ev.audio) if ev.audio else None,
                meta=ev.meta,
            )
        )

    return PipelineTurnResponse(
        events=events,
        sentences=sentences,
        full_text="".join(tokens),
    )
