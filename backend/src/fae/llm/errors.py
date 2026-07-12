"""Normalised LLM error type. Lives in its own module to avoid circular
imports between client.py and provider.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMError(Exception):
    """Normalised LLM failure. `code` is a short string the UI can switch on."""

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"[{self.code}] {self.message}"
