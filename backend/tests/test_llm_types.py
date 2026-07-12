"""Tests for fae.llm.types — Pydantic model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fae.llm.types import (
    ChatMessage,
    ChatRequest,
    LLMConfig,
)


def test_llm_config_defaults() -> None:
    cfg = LLMConfig(api_key="sk-test")
    assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode"
    assert cfg.model == "qwen3-max"


def test_llm_config_rejects_empty_api_key() -> None:
    with pytest.raises(ValidationError):
        LLMConfig(api_key="")


def test_chat_message_accepts_all_roles() -> None:
    for role in ("system", "user", "assistant"):
        m = ChatMessage(role=role, content="hi")
        assert m.role == role


def test_chat_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="hi")  # type: ignore[arg-type]


def test_chat_request_requires_at_least_one_message() -> None:
    cfg = LLMConfig(api_key="sk-test")
    with pytest.raises(ValidationError):
        ChatRequest(config=cfg, messages=[])


def test_chat_request_temperature_bounds() -> None:
    cfg = LLMConfig(api_key="sk-test")
    ChatRequest(
        config=cfg,
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.0,
    )
    ChatRequest(
        config=cfg,
        messages=[ChatMessage(role="user", content="hi")],
        temperature=2.0,
    )
    with pytest.raises(ValidationError):
        ChatRequest(
            config=cfg,
            messages=[ChatMessage(role="user", content="hi")],
            temperature=-0.1,
        )
    with pytest.raises(ValidationError):
        ChatRequest(
            config=cfg,
            messages=[ChatMessage(role="user", content="hi")],
            temperature=2.1,
        )
