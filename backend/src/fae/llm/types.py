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
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="OpenAI-compatible base URL (include /v1).",
    )
    api_key: str = Field(
        default="",
        description="Provider API key (optional when server DASHSCOPE/PROACTIVE_LLM is set).",
    )
    model: str = Field(default="qwen3-max", description="Model name to invoke.")
    # MiniMax-M3 / compatible: auto=omit, disabled|adaptive → extra_body.thinking.type
    thinking: Literal["auto", "disabled", "adaptive"] = Field(
        default="auto",
        description="Provider thinking/reasoning mode (MiniMax-compatible).",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Extra HTTP headers sent on every request "
        "(e.g. anthropic-beta, X-Request-ID, trace headers).",
    )
    context_window: int | None = Field(
        default=None,
        ge=128,
        description="Provider context window size in tokens. "
        "Used for client-side prompt budgeting. None disables budgeting.",
    )
    prompt_cache_key: str | None = Field(
        default=None,
        max_length=128,
        description="Provider-specific prompt cache key (OpenAI/Azure). "
        "Bind to session_id to keep prefix-cache locality.",
    )


class ChatMessage(BaseModel):
    """A single turn in a chat history."""

    role: Literal["system", "user", "assistant"]
    content: str


class ToolCall(BaseModel):
    """One OpenAI-compatible tool call from the model."""

    id: str = ""
    name: str
    arguments: str = "{}"


class ChatRequest(BaseModel):
    """Text-only chat completion request.

    The full voice pipeline (STT → LLM → TTS) lands in later checkpoints.
    """

    config: LLMConfig
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    # Optional memory bucket id (not sent to the LLM provider).
    session_id: str | None = None
    # Optional OpenAI-compatible tools (Phase 3 request_skill).
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None


class TokenUsage(BaseModel):
    """Normalised token usage across providers.

    Provider-agnostic fields:
    - prompt_tokens / completion_tokens / total_tokens
    - cached_tokens: tokens served from prefix / prompt cache (if reported)
    - cache_creation_tokens: tokens written into a 1h cache (Anthropic)
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_creation_tokens: int | None = None


class ChatResponse(BaseModel):
    """Assistant turn returned to the caller."""

    content: str
    model: str
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
