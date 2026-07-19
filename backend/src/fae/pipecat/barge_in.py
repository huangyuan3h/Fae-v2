"""Barge-in (interrupt) control for TTS playback.

When the user starts speaking during assistant playback, we stop TTS and
clear the pending sentence queue — the DEVELOPMENT_PLAN barge-in contract.
"""

from __future__ import annotations

import asyncio
from collections import deque


class BargeInController:
    """Track playback state and honour interrupt signals."""

    def __init__(self) -> None:
        self._playing = False
        self._interrupted = asyncio.Event()
        self._queue: deque[str] = deque()

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def interrupted(self) -> bool:
        return self._interrupted.is_set()

    def enqueue(self, sentence: str) -> None:
        if sentence:
            self._queue.append(sentence)

    def pop_next(self) -> str | None:
        if self._interrupted.is_set() or not self._queue:
            return None
        return self._queue.popleft()

    def start_playback(self) -> None:
        self._playing = True
        self._interrupted.clear()

    def stop_playback(self) -> None:
        self._playing = False

    def on_user_speech_during_playback(self) -> None:
        """Hook matching the plan name: stop TTS + clear the queue."""
        self._interrupted.set()
        self._playing = False
        self._queue.clear()

    def reset(self) -> None:
        self._interrupted.clear()
        self._playing = False
        self._queue.clear()
