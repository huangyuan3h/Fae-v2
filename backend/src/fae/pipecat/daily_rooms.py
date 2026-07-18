"""Daily room minting via Pipecat's runner helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger("fae.pipecat.daily")


@dataclass(frozen=True)
class DailyRoom:
    room_url: str
    token: str


async def create_daily_room(api_key: str) -> DailyRoom:
    """Create a temporary Daily room + meeting token."""
    from pipecat.runner.daily import configure

    async with aiohttp.ClientSession() as session:
        config = await configure(session, api_key=api_key)
    # DailyRoomConfig exposes room_url + token
    room_url = getattr(config, "room_url", None) or getattr(config, "url", None)
    token = getattr(config, "token", None)
    if not room_url or not token:
        raise RuntimeError(f"Unexpected Daily config shape: {config!r}")
    logger.info("Created Daily room %s", room_url)
    return DailyRoom(room_url=room_url, token=token)
