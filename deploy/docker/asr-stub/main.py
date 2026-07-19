"""Minimal ASR stub so docker-compose can reach a healthy vllm-asr service
without a GPU. Returns a canned transcription for smoke tests.
"""

from __future__ import annotations

from fastapi import FastAPI, File, UploadFile

app = FastAPI(title="FAE ASR Stub")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "asr-stub"}


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    _ = await file.read()
    # Echo a fixed phrase so the text pipeline can smoke-test ASR wiring.
    return {"text": "你好", "model": "asr-stub"}
