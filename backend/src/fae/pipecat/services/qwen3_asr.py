"""Qwen3-ASR client (HTTP stub target).

Talks to whatever sits at Settings.vllm_asr_url — the compose ASR stub or a
real vLLM-Omni deployment.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("fae.pipecat.asr")


class Qwen3ASRService:
    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def transcribe(self, audio: bytes, filename: str = "audio.wav") -> str:
        url = f"{self._base_url}/v1/audio/transcriptions"
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            files = {"file": (filename, audio, "audio/wav")}
            resp = await client.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
        text = data.get("text") or ""
        logger.debug("ASR transcribed %d bytes → %r", len(audio), text[:80])
        return text
