"""Pydantic models for LLM requests and responses.

Kept intentionally narrow — only the fields we actually use. The OpenAI
SDK has many more knobs, but exposing them all at our boundary would
make the API harder to evolve. Add fields on demand.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Connection settings for one LLM provider.

    Sent from the UI on every request — the backend never persists API keys.
    """

    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode",
        description="OpenAI-compatible chat completions endpoint.",
    )
    api_key: str = Field(min_length=1, description="Provider API key.")
    model: str = Field(default="qwen3-max", description="Model name to invoke.")


class ChatMessage(BaseModel):
    """A single turn in a chat history."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Text-only chat completion request.

    The full voice pipeline (STT → LLM → TTS) lands in later checkpoints.
    """

    config: LLMConfig
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    """Assistant turn returned to the caller."""

    content: str
    model: str
    usage: dict[str, int] | None = None
