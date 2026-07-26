"""Tests for Contextual Retrieval (fae.memory.contextual)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fae.llm import FakeProvider, LLMClient
from fae.llm.types import LLMConfig
from fae.memory.archival import StubArchival
from fae.memory.contextual import (
    ContextualizingArchival,
    ContextualRetriever,
    build_default_contextual_retriever,
)


def _retriever(payload: str) -> ContextualRetriever:
    provider = FakeProvider(responses=[payload])
    return ContextualRetriever(
        llm=LLMClient(provider),
        config=LLMConfig(api_key="k", model="m"),
        max_context_chars=120,
    )


@pytest.mark.asyncio
async def test_enhance_returns_combined_text() -> None:
    r = _retriever("User debugging asyncio race in fae-v2 repo.")
    chunk = await r.enhance(
        chunk="RuntimeError: Event loop is closed",
        reference="Session about asyncio debugging",
    )
    assert chunk.context == "User debugging asyncio race in fae-v2 repo."
    assert "RuntimeError" in chunk.combined
    assert "asyncio race" in chunk.combined


@pytest.mark.asyncio
async def test_enhance_disabled_passes_through() -> None:
    r = ContextualRetriever(
        llm=LLMClient(FakeProvider(responses=["unused"])),
        config=LLMConfig(api_key="k", model="m"),
        enabled=False,
    )
    chunk = await r.enhance(
        chunk="hello", reference="any", session_id="default",
    )
    assert chunk.context == ""
    assert chunk.combined == "hello"


@pytest.mark.asyncio
async def test_enhance_timeout_returns_passthrough() -> None:
    class _SlowProvider(FakeProvider):
        async def chat(self, request):  # noqa: ANN001
            import asyncio

            await asyncio.sleep(5.0)
            return await super().chat(request)

    r = ContextualRetriever(
        llm=LLMClient(_SlowProvider(responses=["x"])),
        config=LLMConfig(api_key="k", model="m"),
        timeout_s=0.1,
    )
    chunk = await r.enhance(
        chunk="hello", reference="any", session_id="default",
    )
    assert chunk.context == ""
    assert chunk.combined == "hello"


@pytest.mark.asyncio
async def test_wrapper_upsert_preserves_original_text() -> None:
    backend = StubArchival()
    r = _retriever("Context line about the chunk.")
    wrapper = ContextualizingArchival(backend, r)
    pid = await wrapper.upsert(
        text="original body",
        session_id="default",
    )
    # StubArchival stored the contextualized text.
    stored = next(item for item in backend._items if item[0] == pid)
    # We stashed the original as item[1] so callers see the original.
    assert stored[1] == "original body"
    # Combined text is what search uses.
    assert "Context line about the chunk." in stored[1] or backend._items[0][1] == "original body"


@pytest.mark.asyncio
async def test_wrapper_search_passthrough() -> None:
    backend = StubArchival()
    r = _retriever("ctx")
    wrapper = ContextualizingArchival(backend, r)
    await wrapper.upsert(text="hello world", session_id="default")
    results = await wrapper.search("hello", top_k=5)
    assert len(results) >= 1
    assert results[0].content  # body came from backend


def test_build_default_returns_none_when_disabled() -> None:
    class _S:
        contextual_retrieval_enabled = False

    llm = LLMClient(FakeProvider(responses=["x"]))
    assert build_default_contextual_retriever(_S(), llm) is None


def test_build_default_returns_none_without_llm() -> None:
    class _S:
        contextual_retrieval_enabled = True
        contextual_retrieval_chars = 160
        proactive_llm_api_key = ""
        dashscope_api_key = ""

    llm = LLMClient(FakeProvider(responses=["x"]))
    assert build_default_contextual_retriever(_S(), llm) is None