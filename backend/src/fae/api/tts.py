"""HTTP TTS surface — Qwen3-TTS (DashScope) without Daily."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from fae.config import Settings
from fae.pipecat.services.qwen3_tts import Qwen3TTSService
from fae.tts.speakable import to_speakable_text
from fae.tts.wav import pcm16_mono_to_wav

logger = logging.getLogger("fae.tts")

router = APIRouter(prefix="/api/tts", tags=["tts"])

# DashScope flash models are happier with shorter utterances.
_MAX_CHARS = 2000


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/status")
async def tts_status(settings: Annotated[Settings, Depends(_settings)]) -> dict:
    configured = bool((settings.dashscope_api_key or "").strip())
    return {
        "backend": "qwen3-tts",
        "configured": configured,
        "model": settings.tts_model,
        "voice": settings.tts_voice,
        "sample_rate": settings.tts_sample_rate,
        "hint": (
            "Qwen3-TTS ready"
            if configured
            else "Set DASHSCOPE_API_KEY in root .env and restart backend"
        ),
    }


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    settings: Annotated[Settings, Depends(_settings)],
) -> Response:
    """Synthesize speakable text with Qwen3-TTS; return audio/wav."""
    api_key = (settings.dashscope_api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "tts_not_configured",
                "message": "DASHSCOPE_API_KEY not set",
            },
        )

    plain = to_speakable_text(body.text)
    if not plain:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_text", "message": "Nothing left to speak"},
        )
    if len(plain) > _MAX_CHARS:
        plain = plain[:_MAX_CHARS].rstrip() + "…"

    voice = (body.voice or settings.tts_voice or "Cherry").strip()
    tts = Qwen3TTSService(
        api_key=api_key,
        sample_rate=settings.tts_sample_rate,
        model=settings.tts_model,
        voice=voice,
        language_type=settings.tts_language,
    )
    try:
        pcm = await tts.synthesize(plain, raise_on_error=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("Qwen3-TTS failed")
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_failed", "message": str(e)},
        ) from e

    if not pcm:
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_empty", "message": "TTS returned no audio"},
        )

    wav = pcm16_mono_to_wav(pcm, sample_rate=settings.tts_sample_rate)
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "X-FAE-TTS-Backend": "qwen3-tts",
            "X-FAE-TTS-Voice": voice,
            "Cache-Control": "no-store",
        },
    )
