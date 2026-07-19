"""HTTP TTS surface — local OpenAI-compatible only (no cloud TTS)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from fae.config import Settings
from fae.tts.local_client import LocalTTSClient, LocalTTSError
from fae.tts.speakable import to_speakable_text
from fae.tts.stub_server import synthesize_wav

logger = logging.getLogger("fae.tts")

router = APIRouter(prefix="/api/tts", tags=["tts"])

_MAX_CHARS = 2000


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _local_client(settings: Settings) -> LocalTTSClient:
    return LocalTTSClient(
        base_url=settings.vllm_tts_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        sample_rate=settings.tts_sample_rate,
        response_format=settings.tts_response_format,
        timeout_s=settings.tts_timeout_s,
    )


@router.get("/status")
async def tts_status(settings: Annotated[Settings, Depends(_settings)]) -> dict:
    if settings.tts_embed_stub:
        return {
            "backend": "local",
            "configured": True,
            "embedded": True,
            "natural_speech": False,
            "model": settings.tts_model,
            "voice": settings.tts_voice,
            "sample_rate": settings.tts_sample_rate,
            "url": settings.vllm_tts_url,
            "hint": (
                "Stub only (beep). UI uses browser speech for words. "
                "For natural local TTS: TTS_EMBED_STUB=false + real server — "
                "doc/LOCAL_TTS.md"
            ),
        }

    client = _local_client(settings)
    reachable = await client.health()
    return {
        "backend": "local",
        "configured": reachable,
        "embedded": False,
        "natural_speech": reachable,
        "model": settings.tts_model,
        "voice": settings.tts_voice,
        "sample_rate": settings.tts_sample_rate,
        "url": settings.vllm_tts_url,
        "hint": (
            f"Local TTS ready at {settings.vllm_tts_url}"
            if reachable
            else (
                f"Start local TTS at {settings.vllm_tts_url} — see doc/LOCAL_TTS.md"
            )
        ),
    }


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    settings: Annotated[Settings, Depends(_settings)],
) -> Response:
    """Synthesize speakable text; return audio for the browser player."""
    plain = to_speakable_text(body.text)
    if not plain:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_text", "message": "Nothing left to speak"},
        )
    if len(plain) > _MAX_CHARS:
        plain = plain[:_MAX_CHARS].rstrip() + "…"

    voice = (body.voice or settings.tts_voice or "Cherry").strip()

    if settings.tts_embed_stub:
        audio = synthesize_wav(plain, sample_rate=settings.tts_sample_rate)
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={
                "X-FAE-TTS-Backend": "local-embedded",
                "X-FAE-TTS-Voice": voice,
                "Cache-Control": "no-store",
            },
        )

    client = _local_client(settings)
    try:
        audio, media_type = await client.synthesize(plain, voice=voice)
    except LocalTTSError as e:
        logger.warning("Local TTS failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "local_tts_unavailable",
                "message": str(e),
            },
        ) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Local TTS failed")
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_failed", "message": str(e)},
        ) from e

    return Response(
        content=audio,
        media_type=media_type or "audio/wav",
        headers={
            "X-FAE-TTS-Backend": "local",
            "X-FAE-TTS-Voice": voice,
            "Cache-Control": "no-store",
        },
    )
