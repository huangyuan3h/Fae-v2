"""OpenAI-compatible local TTS client (Qwen3-TTS / CosyVoice / stub).

Talks to POST {base}/audio/speech — no cloud API key required.
"""

from __future__ import annotations

import logging

import httpx

from fae.tts.wav import pcm16_mono_to_wav

logger = logging.getLogger("fae.tts")


class LocalTTSError(RuntimeError):
    pass


class LocalTTSClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str = "qwen3-tts",
        voice: str = "Cherry",
        sample_rate: int = 24000,
        response_format: str = "wav",
        timeout_s: float = 60.0,
        api_key: str = "local",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.sample_rate = sample_rate
        self.response_format = response_format
        self.timeout_s = timeout_s
        self.api_key = api_key or "local"

    @property
    def speech_url(self) -> str:
        # Accept either http://host:8003 or http://host:8003/v1
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/audio/speech"
        return f"{base}/v1/audio/speech"

    @property
    def models_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/models"
        return f"{self.base_url}/v1/models"

    async def health(self) -> bool:
        """Return True only if an OpenAI-compatible TTS surface is present.

        Do not treat a generic app `/health` (e.g. FAE backend) as TTS readiness.
        """
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                resp = await client.get(self.models_url)
            except httpx.HTTPError:
                return False
            if resp.status_code >= 400:
                return False
            try:
                body = resp.json()
            except ValueError:
                return False
            # OpenAI list: {"object":"list","data":[...]} or at least a data array
            if isinstance(body, dict) and isinstance(body.get("data"), list):
                return True
            return False

    async def synthesize(
        self, text: str, *, voice: str | None = None
    ) -> tuple[bytes, str]:
        """Return (audio_bytes, media_type). Prefer WAV for browser playback."""
        if not text.strip():
            return b"", "audio/wav"

        payload = {
            "model": self.model,
            "input": text,
            "voice": voice or self.voice,
            "response_format": self.response_format,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    self.speech_url, json=payload, headers=headers
                )
        except httpx.HTTPError as e:
            raise LocalTTSError(
                f"Cannot reach local TTS at {self.speech_url}: {e}"
            ) from e

        if resp.status_code >= 400:
            raise LocalTTSError(
                f"Local TTS HTTP {resp.status_code}: {resp.text[:300]}"
            )

        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
        data = resp.content
        if not data:
            raise LocalTTSError("Local TTS returned empty audio")

        # Normalize PCM → WAV when servers stream raw PCM
        if content_type in ("audio/pcm", "application/octet-stream") or (
            self.response_format == "pcm" and not data.startswith(b"RIFF")
        ):
            data = pcm16_mono_to_wav(data, sample_rate=self.sample_rate)
            content_type = "audio/wav"
        elif not content_type:
            content_type = (
                "audio/wav"
                if data.startswith(b"RIFF")
                else "audio/mpeg"
                if data[:3] == b"ID3" or data[:2] == b"\xff\xfb"
                else "application/octet-stream"
            )
        return data, content_type
