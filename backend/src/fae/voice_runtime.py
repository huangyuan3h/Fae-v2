"""Process-local registry for active voice sessions.

Keeps Daily bot tasks off Starlette BackgroundTasks (those are awaited
after the HTTP response and bind request lifetime to the call). Phase 2
memory hooks will attach to the same session_id → handle map.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fae.pipecat.barge_in import BargeInController

logger = logging.getLogger("fae.voice_runtime")

InterruptFn = Callable[[], Awaitable[None]]


@dataclass
class VoiceHandle:
    session_id: str
    barge_in: BargeInController = field(default_factory=BargeInController)
    daily_task: asyncio.Task[None] | None = None
    room_url: str | None = None
    interrupt_pipeline: InterruptFn | None = None


class VoiceRuntime:
    """session_id → handle (barge-in + optional Daily task)."""

    def __init__(self) -> None:
        self._handles: dict[str, VoiceHandle] = {}

    def register(self, session_id: str, *, room_url: str | None = None) -> VoiceHandle:
        handle = VoiceHandle(session_id=session_id, room_url=room_url)
        self._handles[session_id] = handle
        return handle

    def get(self, session_id: str) -> VoiceHandle | None:
        return self._handles.get(session_id)

    def spawn(self, session_id: str, coro: Awaitable[None]) -> asyncio.Task[None]:
        handle = self._handles.get(session_id)
        if handle is None:
            handle = self.register(session_id)

        async def _runner() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                logger.info("Daily bot cancelled session=%s", session_id)
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Daily bot crashed session=%s", session_id)
            finally:
                current = self._handles.get(session_id)
                if current is not None and current.daily_task is asyncio.current_task():
                    current.daily_task = None
                    current.interrupt_pipeline = None

        task = asyncio.create_task(_runner(), name=f"daily-bot-{session_id}")
        handle.daily_task = task
        return task

    async def interrupt(self, session_id: str) -> bool:
        """Signal barge-in for a session. Returns False if unknown."""
        handle = self._handles.get(session_id)
        if handle is None:
            return False
        handle.barge_in.on_user_speech_during_playback()
        if handle.interrupt_pipeline is not None:
            try:
                await handle.interrupt_pipeline()
            except Exception:  # noqa: BLE001
                logger.exception("Pipeline interrupt failed session=%s", session_id)
        return True

    async def shutdown(self) -> None:
        tasks = [
            h.daily_task
            for h in self._handles.values()
            if h.daily_task is not None and not h.daily_task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._handles.clear()
