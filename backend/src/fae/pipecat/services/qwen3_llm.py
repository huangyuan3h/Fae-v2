"""Qwen3 LLM service — thin adapter over fae.llm.LLMClient.

Eventually this becomes a Pipecat FrameProcessor; for the Phase 1.3 minimal
attempt we expose async iterators that the TextPipelineBot consumes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig


class Qwen3LLMService:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def stream_reply(
        self,
        *,
        user_text: str,
        config: LLMConfig,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=user_text))
        request = ChatRequest(config=config, messages=messages)
        async for token in self._client.stream(request):
            yield token
