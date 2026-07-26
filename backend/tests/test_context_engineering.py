"""Tests for LLM usage extraction, byte-stable ordering, and prompt budgeting."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from fae.agent.prepare import prepare_chat_request
from fae.llm.client import LLMClient, _accumulate
from fae.llm.provider import (
    OpenAICompatibleProvider,
    _extract_usage,
    _extra_body,
)
from fae.llm.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMConfig,
    TokenUsage,
)
from fae.memory.core_budget import clip_recent_turns_for_budget


def test_extract_usage_handles_prompt_tokens_details() -> None:
    details = SimpleNamespace(cached_tokens=42)
    usage = SimpleNamespace(
        prompt_tokens=100, completion_tokens=20, total_tokens=120,
        prompt_tokens_details=details,
    )
    parsed = _extract_usage(usage)
    assert parsed is not None
    assert parsed.prompt_tokens == 100
    assert parsed.cached_tokens == 42


def test_extract_usage_handles_anthropic_cache_creation() -> None:
    usage = SimpleNamespace(
        prompt_tokens=80, completion_tokens=15, total_tokens=95,
        cache_creation_input_tokens=30,
    )
    parsed = _extract_usage(usage)
    assert parsed is not None
    assert parsed.cache_creation_tokens == 30


def test_extract_usage_handles_deepseek_hit_tokens() -> None:
    usage = SimpleNamespace(
        prompt_tokens=200, completion_tokens=50, total_tokens=250,
        prompt_cache_hit_tokens=120,
    )
    parsed = _extract_usage(usage)
    assert parsed is not None
    assert parsed.cached_tokens == 120


def test_extract_usage_returns_none_when_empty() -> None:
    assert _extract_usage(None) is None
    assert _extract_usage(SimpleNamespace()) is None


def test_extra_body_combines_thinking_and_cache_key() -> None:
    cfg = LLMConfig(
        thinking="adaptive",
        prompt_cache_key="session-1",
    )
    body = _extra_body(cfg)
    assert body is not None
    assert body.get("thinking") == {"type": "adaptive"}
    assert body.get("prompt_cache_key") == "session-1"


def test_extra_body_omits_when_disabled() -> None:
    cfg = LLMConfig(thinking="auto", prompt_cache_key=None)
    assert _extra_body(cfg) is None


def test_accumulate_sums_counters() -> None:
    target: dict[str, int] = {}
    _accumulate(
        target,
        TokenUsage(
            prompt_tokens=100, completion_tokens=20, total_tokens=120,
            cached_tokens=10,
        ),
    )
    _accumulate(
        target,
        TokenUsage(
            prompt_tokens=50, completion_tokens=10, total_tokens=60,
            cached_tokens=5,
        ),
    )
    assert target == {
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "total_tokens": 180,
        "cached_tokens": 15,
        "calls": 2,
    }


def test_clip_recent_turns_preserves_head_and_keeps_tail() -> None:
    text = (
        "[persona] hi\n"
        "[human] user\n"
        "[current] c\n"
        "[recent_turns]\n"
        + ("\n".join(f"line {i}" for i in range(200)))
    )
    budget = 200
    clipped = clip_recent_turns_for_budget(text, char_budget=budget)
    assert len(clipped) <= budget + 32
    assert "[persona]" in clipped
    assert "[recent_turns]" in clipped
    assert "line 199" in clipped
    assert "line 0" not in clipped


def test_clip_recent_turns_no_op_when_within_budget() -> None:
    text = "[persona] small\n[recent_turns]\nshort"
    assert clip_recent_turns_for_budget(text, char_budget=10_000) == text


def test_openai_provider_passes_extra_headers() -> None:
    captured: dict = {}

    class _StubResp:
        choices = [
            SimpleNamespace(
                message=SimpleNamespace(content="hi", tool_calls=None),
            )
        ]
        model = "m"
        usage = None

    class _StubCompletions:
        async def create(self, **kw):  # noqa: ANN001
            captured.update(kw)
            return _StubResp()

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

        def __init__(self, **kw) -> None:
            captured["client_kwargs"] = kw

        async def close(self) -> None:
            pass

    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **kw: _StubClient(**kw)  # type: ignore[assignment]
    try:
        provider = OpenAICompatibleProvider()
        req = ChatRequest(
            config=LLMConfig(
                api_key="k", model="m",
                headers={"X-Trace-Id": "abc", "anthropic-beta": "x"},
                prompt_cache_key="default",
            ),
            messages=[ChatMessage(role="user", content="hi")],
        )
        asyncio.run(provider.chat(req))
    finally:
        provider_mod.AsyncOpenAI = original

    assert captured["client_kwargs"].get("default_headers") == {
        "X-Trace-Id": "abc", "anthropic-beta": "x",
    }
    assert captured.get("extra_body", {}).get("prompt_cache_key") == "default"


@pytest.mark.asyncio
async def test_prepare_chat_request_budgets_recent_turns(tmp_path: Path) -> None:
    """prepare_chat_request should soft-trim [recent_turns] when over budget."""
    from fae.memory.embedded import EmbeddedMemoryClient
    from fae.memory.recall_store import RecallStore

    recall = RecallStore(tmp_path / "mem.recall.db")
    client = EmbeddedMemoryClient(
        tmp_path / "mem.db",
        recall_store=recall,
    )
    await client.ensure_agent()
    for i in range(60):
        await client.append_recall(
            "default",
            f"question {i} " + ("x" * 50),
            f"answer {i} " + ("y" * 50),
        )

    from fae.pipecat.services.letta_memory import LettaMemoryService

    memory = LettaMemoryService(
        client,
        recent_limit=20, events_limit=0, facts_top_k=2,
    )
    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m", context_window=2048),
        messages=[ChatMessage(role="user", content="hi")],
    )
    prepared, _, _ = await prepare_chat_request(
        req,
        session_id="default",
        memory=memory,
        skills=None,
        reserve_tokens=512,
    )
    sys_chars = sum(len(m.content) for m in prepared.messages if m.role == "system")
    budget = (2048 - 512) * 4
    # Without budgeting the total would be ~4500 chars; with budgeting
    # we expect well under the budget.
    assert sys_chars <= budget + 600
    assert "[recent_turns]" in prepared.messages[0].content
    # Last few recent turns should still be present (newest kept).
    assert "question 59" in prepared.messages[0].content
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_llm_client_records_usage(tmp_path: Path) -> None:
    from fae.llm.provider import FakeProvider

    provider = FakeProvider(responses=["hi"])
    client = LLMClient(provider)
    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="hello")],
    )
    # Stub a usage report.
    async def fake_chat(_req):
        return ChatResponse(
            content="ok", model="m",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
                cached_tokens=4,
            ),
        )
    provider.chat = fake_chat  # type: ignore[assignment]
    await client.chat(req)
    snap = client.usage_snapshot()
    assert snap["prompt_tokens"] == 10
    assert snap["cached_tokens"] == 4
    assert snap["calls"] == 1


# ── R1: cache_control (Anthropic prompt cache) ────────────────────────


def test_cache_control_marker_resolves_modes() -> None:
    from fae.llm.provider import _cache_control_marker

    assert _cache_control_marker(None) == {"type": "ephemeral"}
    assert _cache_control_marker("auto") == {"type": "ephemeral"}
    assert _cache_control_marker("off") is None
    assert _cache_control_marker("ephemeral-5m") == {
        "type": "ephemeral", "ttl": "5m",
    }
    assert _cache_control_marker("ephemeral-1h") == {
        "type": "ephemeral", "ttl": "1h",
    }


def test_cache_control_detects_anthropic_endpoint() -> None:
    from fae.llm.provider import _is_anthropic_endpoint

    assert _is_anthropic_endpoint(
        LLMConfig(base_url="https://api.anthropic.com/v1")
    )
    assert _is_anthropic_endpoint(
        LLMConfig(
            base_url="https://dashscope.aliyuncs.com/anthropic-compatible/v1"
        )
    )
    assert _is_anthropic_endpoint(
        LLMConfig(
            base_url="https://gateway.example.com/v1",
            headers={"anthropic-version": "2023-06-01"},
        )
    )
    assert not _is_anthropic_endpoint(
        LLMConfig(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    )
    assert not _is_anthropic_endpoint(
        LLMConfig(base_url="https://api.openai.com/v1")
    )


def test_extra_body_merges_cache_control_marker() -> None:
    from fae.llm.provider import _extra_body

    cfg = LLMConfig(
        base_url="https://api.anthropic.com/v1",
        thinking="adaptive",
        prompt_cache_key="s-1",
        cache_control="ephemeral-1h",
    )
    body = _extra_body(cfg)
    assert body is not None
    assert body.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}
    assert body.get("thinking") == {"type": "adaptive"}
    assert body.get("prompt_cache_key") == "s-1"


def test_apply_cache_control_injects_system_marker_and_tool_marker() -> None:
    from fae.llm.provider import _apply_cache_control_to_kwargs

    cfg = LLMConfig(
        base_url="https://api.anthropic.com/v1",
        cache_control="ephemeral-1h",
        prompt_cache_key="default",
    )
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": "you are FAE"},
            {"role": "user", "content": "hi"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "memory_search"}},
            {"type": "function", "function": {"name": "schedule_create"}},
        ],
    }
    _apply_cache_control_to_kwargs(
        cfg, kwargs, messages=kwargs["messages"], tools=kwargs["tools"],
    )
    # Last tool gets the marker; first is left alone so the API can
    # hash the array as a single cache segment.
    assert kwargs["tools"][0].get("cache_control") is None
    assert kwargs["tools"][-1]["cache_control"] == {
        "type": "ephemeral", "ttl": "1h",
    }
    # System pulled out as Anthropic array; last block carries the marker.
    sys_block = kwargs["system"]
    assert isinstance(sys_block, list)
    assert sys_block[-1]["cache_control"] == {
        "type": "ephemeral", "ttl": "1h",
    }
    # User message survived in messages list.
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    # extra_body also carries the marker for off-spec gateways.
    assert kwargs["extra_body"]["cache_control"] == {
        "type": "ephemeral", "ttl": "1h",
    }


def test_cache_control_off_skips_marker() -> None:
    from fae.llm.provider import _apply_cache_control_to_kwargs

    cfg = LLMConfig(
        base_url="https://api.anthropic.com/v1",
        cache_control="off",
    )
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": "you are FAE"},
            {"role": "user", "content": "hi"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "memory_search"}},
        ],
    }
    _apply_cache_control_to_kwargs(
        cfg, kwargs, messages=kwargs["messages"], tools=kwargs["tools"],
    )
    assert "system" not in kwargs
    assert kwargs["tools"][0].get("cache_control") is None
    assert "cache_control" not in kwargs.get("extra_body", {})


def test_cache_control_skipped_on_non_anthropic_endpoint() -> None:
    from fae.llm.provider import _apply_cache_control_to_kwargs

    cfg = LLMConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        cache_control="ephemeral-1h",
    )
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": "you are FAE"},
            {"role": "user", "content": "hi"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "memory_search"}},
        ],
    }
    _apply_cache_control_to_kwargs(
        cfg, kwargs, messages=kwargs["messages"], tools=kwargs["tools"],
    )
    assert "system" not in kwargs
    assert kwargs["tools"][0].get("cache_control") is None