"""HTTP TTS surface — local OpenAI-compatible only (no browser / cloud TTS)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from fae.config import Settings, get_settings
from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.speakable import clip_for_local_tts, to_speakable_text

logger = logging.getLogger("fae.tts")

router = APIRouter(prefix="/api/tts", tags=["tts"])

# Per-request safety cap; UI sends sentence chunks for long replies.
_MAX_CHARS = 120


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    language: str | None = None


def _live_settings(request: Request) -> Settings:
    """Re-read .env so VLLM_TTS_URL changes apply without a full process recycle."""
    get_settings.cache_clear()
    settings = get_settings()
    request.app.state.settings = settings
    return settings


def _local_client(settings: Settings) -> LocalTTSClient:
    return LocalTTSClient(
        base_url=settings.vllm_tts_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        sample_rate=settings.tts_sample_rate,
        response_format=settings.tts_response_format,
        timeout_s=settings.tts_timeout_s,
        language=settings.tts_language,
        speed=settings.tts_speed,
    )


@router.get("/status")
async def tts_status(settings: Annotated[Settings, Depends(_live_settings)]) -> dict:
    client = _local_client(settings)
    reachable = await client.health()
    return {
        "backend": "local",
        "configured": reachable,
        "embedded": False,
        "natural_speech": reachable,
        "model": settings.tts_model,
        "voice": settings.tts_voice,
        "language": settings.tts_language,
        "speed": settings.tts_speed,
        "sample_rate": settings.tts_sample_rate,
        "url": settings.vllm_tts_url,
        "speech_url": client.speech_url,
        "hint": (
            f"Local TTS ready at {settings.vllm_tts_url}"
            if reachable
            else (
                f"No TTS server at {client.speech_url}. "
                "Start Qwen3-TTS / CosyVoice on that port — doc/LOCAL_TTS.md"
            )
        ),
    }


@router.get("/voices")
async def tts_voices(settings: Annotated[Settings, Depends(_live_settings)]) -> dict:
    client = _local_client(settings)
    result = await client.list_voices()
    return {
        "voices": result["voices"],
        "languages": result["languages"],
        "source": result["source"],
        "defaults": {
            "voice": settings.tts_voice,
            "language": settings.tts_language,
            "speed": settings.tts_speed,
        },
    }


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    settings: Annotated[Settings, Depends(_live_settings)],
) -> Response:
    """Proxy to VLLM_TTS_URL; UI always calls this FAE endpoint (:8000)."""
    plain = clip_for_local_tts(to_speakable_text(body.text), max_chars=_MAX_CHARS)
    if not plain:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_text", "message": "Nothing left to speak"},
        )

    voice = (body.voice or settings.tts_voice or "Vivian").strip()
    language = (body.language or settings.tts_language or "Chinese").strip()
    speed = (
        float(body.speed)
        if body.speed is not None
        else float(settings.tts_speed)
    )

    client = _local_client(settings)
    try:
        audio, media_type = await client.synthesize(
            plain, voice=voice, speed=speed, language=language
        )
    except LocalTTSError as e:
        logger.warning("Local TTS failed (%s): %s", client.speech_url, e)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "local_tts_unavailable",
                "message": str(e),
                "upstream": client.speech_url,
            },
        ) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Local TTS failed")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "tts_failed",
                "message": str(e),
                "upstream": client.speech_url,
            },
        ) from e

    return Response(
        content=audio,
        media_type=media_type or "audio/wav",
        headers={
            "X-FAE-TTS-Backend": "local",
            "X-FAE-TTS-Upstream": client.speech_url,
            "X-FAE-TTS-Voice": voice,
            "X-FAE-TTS-Speed": f"{speed:.2f}",
            "Cache-Control": "no-store",
        },
    )
