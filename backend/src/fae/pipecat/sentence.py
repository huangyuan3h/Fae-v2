"""Accumulate streaming LLM tokens into speakable sentences."""

from __future__ import annotations

import re

# Split after sentence-ending punctuation (CJK + Latin). Keep the delimiter
# attached to the completed sentence.
_SENTENCE_END = re.compile(r"(?<=[。！？.!?…])")


class SentenceAggregator:
    """Buffer tokens until a sentence boundary is reached.

    Used to feed TTS with whole sentences instead of raw token drips,
    matching the DEVELOPMENT_PLAN SentenceAggregator requirement.
    """

    def __init__(self) -> None:
        self._buf = ""

    def push(self, token: str) -> list[str]:
        """Append a token; return zero or more completed sentences."""
        if not token:
            return []
        self._buf += token
        parts = _SENTENCE_END.split(self._buf)
        if len(parts) == 1:
            return []
        # Last fragment may be incomplete — keep it in the buffer.
        completed = [p for p in parts[:-1] if p.strip()]
        self._buf = parts[-1]
        return completed

    def flush(self) -> str | None:
        """Return any trailing buffered text (no terminal punctuation)."""
        leftover = self._buf.strip()
        self._buf = ""
        return leftover or None

    @property
    def buffer(self) -> str:
        return self._buf
