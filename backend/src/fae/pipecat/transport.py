"""Transport abstractions.

Phase 1 MVP uses browser Web Speech + `/ws/chat` (no WebRTC room required).
`DailyTransportConfig` documents the future Pipecat Daily wiring; minting a
live room still needs `DAILY_API_KEY` and the pipecat Daily bot process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class TransportEvent:
    type: str  # "user_text" | "user_audio_start" | "user_audio_end" | "assistant_audio"
    payload: str | bytes | None = None


@runtime_checkable
class VoiceTransport(Protocol):
    """Minimal surface a bot needs from a realtime transport."""

    async def send_assistant_text(self, text: str) -> None: ...

    async def send_assistant_audio(self, pcm: bytes) -> None: ...


@dataclass
class LocalTransport:
    """In-process transport that records outbound frames for tests / demos."""

    sent_text: list[str] = field(default_factory=list)
    sent_audio: list[bytes] = field(default_factory=list)

    async def send_assistant_text(self, text: str) -> None:
        self.sent_text.append(text)

    async def send_assistant_audio(self, pcm: bytes) -> None:
        self.sent_audio.append(pcm)


@dataclass(frozen=True)
class DailyTransportConfig:
    """Parameters for a future Daily / Pipecat WebRTC session."""

    room_url: str
    token: str
    bot_name: str = "FAE"
