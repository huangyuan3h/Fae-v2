"""LLM abstraction layer.

Exposes a small Protocol-based interface so the rest of the app talks to
"an LLM" without coupling to the OpenAI SDK. Production uses
`OpenAICompatibleProvider` (works for Qwen3, DeepSeek, OpenAI, vLLM, etc. —
any server speaking the OpenAI chat completions protocol). Tests use
`FakeProvider` for hermetic, deterministic behaviour.
"""

from fae.llm.client import LLMClient
from fae.llm.errors import LLMError
from fae.llm.provider import FakeProvider, OpenAICompatibleProvider
from fae.llm.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMConfig,
    ToolCall,
)

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "FakeProvider",
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "OpenAICompatibleProvider",
    "ToolCall",
]
