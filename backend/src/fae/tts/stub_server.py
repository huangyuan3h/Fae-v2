"""Lightweight OpenAI-compatible TTS stub for local development (no GPU).

Can run standalone:
  uv run python -m fae.tts.stub_server   # :8003

Or mount into the main FAE app when Settings.tts_embed_stub is True
(default) so `npm run dev` / backend alone already has TTS.
"""

from __future__ import annotations

import math
import os
import struct
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel, Field

from fae.tts.wav import pcm16_mono_to_wav

app = FastAPI(title="FAE local TTS stub", version="0.1.0")
_SAMPLE_RATE = 24000


class SpeechIn(BaseModel):
    model: str = "qwen3-tts"
    input: str = Field(default="", min_length=0)
    voice: str = "Cherry"
    response_format: str = "wav"


def tone_pcm(text: str, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Generate a short beep train proportional to text length (audible smoke)."""
    duration = min(2.5, 0.25 + 0.04 * max(1, len(text.strip())))
    n = int(sample_rate * duration)
    freq = 440.0
    samples: list[int] = []
    for i in range(n):
        env = min(1.0, i / 800) * min(1.0, (n - i) / 800)
        val = int(12000 * env * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(val)
    return struct.pack(f"<{len(samples)}h", *samples)


def synthesize_wav(text: str, *, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """In-process stub synthesis used by the embedded FAE app."""
    pcm = tone_pcm(text or " ", sample_rate=sample_rate)
    return pcm16_mono_to_wav(pcm, sample_rate=sample_rate)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "backend": "stub"}


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": "qwen3-tts", "object": "model", "owned_by": "fae-stub"},
            {"id": "tts-1", "object": "model", "owned_by": "fae-stub"},
        ],
    }


@app.post("/v1/audio/speech")
async def speech(body: SpeechIn) -> Response:
    text = (body.input or "").strip() or " "
    wav = synthesize_wav(text)
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"X-FAE-TTS-Stub": "1", "X-FAE-TTS-Voice": body.voice},
    )


def mount_stub_routes(parent: FastAPI) -> None:
    """Mount OpenAI-compatible stub routes onto the main FAE app."""
    parent.add_api_route("/health/tts", health, methods=["GET"], tags=["tts-stub"])
    parent.add_api_route("/v1/models", models, methods=["GET"], tags=["tts-stub"])
    parent.add_api_route(
        "/v1/audio/speech", speech, methods=["POST"], tags=["tts-stub"]
    )


def main() -> None:
    host = os.environ.get("FAE_TTS_STUB_HOST", "127.0.0.1")
    port = int(os.environ.get("FAE_TTS_STUB_PORT", "8003"))
    uvicorn.run(
        "fae.tts.stub_server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
