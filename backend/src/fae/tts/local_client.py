"""OpenAI-compatible local TTS client (Qwen3-TTS / CosyVoice / stub).

Talks to POST {base}/audio/speech — no cloud API key required.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from fae.tts.wav import pcm16_mono_to_wav

logger = logging.getLogger("fae.tts")

# Fallback when upstream /voices is unreachable
BUILTIN_VOICES: list[dict[str, str]] = [
    {"id": "Vivian", "name": "Vivian", "language": "Chinese"},
    {"id": "Ryan", "name": "Ryan", "language": "English"},
    {"id": "Serena", "name": "Serena", "language": "Chinese"},
    {"id": "Dylan", "name": "Dylan", "language": "Chinese"},
    {"id": "Eric", "name": "Eric", "language": "Chinese"},
    {"id": "Aiden", "name": "Aiden", "language": "English"},
    {"id": "Uncle_Fu", "name": "Uncle Fu", "language": "Chinese"},
    {"id": "Ono_Anna", "name": "Ono Anna", "language": "Japanese"},
    {"id": "Sohee", "name": "Sohee", "language": "Korean"},
]

BUILTIN_LANGUAGES = [
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Spanish",
    "Russian",
    "Portuguese",
    "Italian",
    "Auto",
]


class LocalTTSError(RuntimeError):
    pass


def _http_client(timeout: float) -> httpx.AsyncClient:
    # trust_env=False: macOS/system HTTP_PROXY must not intercept localhost TTS.
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


class LocalTTSClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str = "tts-1",
        voice: str = "Vivian",
        sample_rate: int = 24000,
        response_format: str = "wav",
        timeout_s: float = 300.0,
        api_key: str = "local",
        language: str = "Chinese",
        speed: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.sample_rate = sample_rate
        self.response_format = response_format
        self.timeout_s = timeout_s
        self.api_key = api_key or "local"
        self.language = language or "Chinese"
        self.speed = float(speed)

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

    @property
    def voices_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/voices"
        return f"{self.base_url}/v1/voices"

    @property
    def health_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url[:-3]}/health"
        return f"{self.base_url.rstrip('/')}/health"

    async def health(self) -> bool:
        """Return True only if an OpenAI-compatible TTS surface is present."""
        async with _http_client(3.0) as client:
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
            return isinstance(body, dict) and isinstance(body.get("data"), list)

    async def upstream_status(self) -> dict[str, Any] | None:
        """Fetch upstream /health for backend name + model_id (best-effort)."""
        async with _http_client(3.0) as client:
            try:
                resp = await client.get(self.health_url)
            except httpx.HTTPError:
                return None
        if resp.status_code >= 400:
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        backend = body.get("backend")
        device = body.get("device")
        return {
            "status": body.get("status"),
            "backend": backend if isinstance(backend, dict) else {},
            "device": device if isinstance(device, dict) else {},
        }

    async def list_voices(self) -> dict[str, Any]:
        """Return {voices, languages, source} from upstream or builtins."""
        async with _http_client(5.0) as client:
            try:
                resp = await client.get(self.voices_url)
            except httpx.HTTPError:
                return {
                    "voices": BUILTIN_VOICES,
                    "languages": BUILTIN_LANGUAGES,
                    "source": "builtin",
                }
        if resp.status_code >= 400:
            return {
                "voices": BUILTIN_VOICES,
                "languages": BUILTIN_LANGUAGES,
                "source": "builtin",
            }
        try:
            body = resp.json()
        except ValueError:
            return {
                "voices": BUILTIN_VOICES,
                "languages": BUILTIN_LANGUAGES,
                "source": "builtin",
            }

        voices: list[dict[str, str]] = []
        raw_voices = body.get("voices") or body.get("data") or []
        if isinstance(raw_voices, list):
            for item in raw_voices:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("id") or item.get("voice_id") or item.get("name") or "")
                if not vid or vid.startswith("clone:"):
                    continue
                voices.append(
                    {
                        "id": vid,
                        "name": str(item.get("name") or vid),
                        "language": str(item.get("language") or "Auto"),
                    }
                )
        languages = body.get("languages")
        if not isinstance(languages, list) or not languages:
            languages = BUILTIN_LANGUAGES
        if not voices:
            voices = BUILTIN_VOICES
        return {
            "voices": voices,
            "languages": [str(x) for x in languages],
            "source": "upstream",
        }

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        language: str | None = None,
    ) -> tuple[bytes, str]:
        """Return (audio_bytes, media_type). Prefer WAV for browser playback."""
        if not text.strip():
            return b"", "audio/wav"

        rate = float(self.speed if speed is None else speed)
        rate = max(0.25, min(4.0, rate))
        payload = {
            "model": self.model,
            "input": text,
            "voice": voice or self.voice,
            "response_format": self.response_format,
            "language": language or self.language,
            "speed": rate,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with _http_client(self.timeout_s) as client:
                resp = await client.post(
                    self.speech_url, json=payload, headers=headers
                )
        except httpx.HTTPError as e:
            raise LocalTTSError(
                f"Cannot reach local TTS at {self.speech_url}: {e}. "
                "Start your Qwen3-TTS / CosyVoice server and check VLLM_TTS_URL."
            ) from e

        if resp.status_code >= 400:
            raise LocalTTSError(
                f"Local TTS HTTP {resp.status_code} from {self.speech_url}: "
                f"{resp.text[:300]}"
            )

        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
        data = resp.content
        if not data:
            raise LocalTTSError(f"Local TTS returned empty audio from {self.speech_url}")

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
