"""Tests for R3 Pipecat LLMContextSummarizer bridge (Daily path)."""

from __future__ import annotations

import pytest


def test_builder_off_when_disabled() -> None:
    from fae.pipecat.summarizer_bridge import build_assistant_aggregator_params

    params = build_assistant_aggregator_params(enabled=False)
    assert params is not None
    assert params.enable_auto_context_summarization is False
    assert params.auto_context_summarization_config is None


def test_builder_on_when_enabled() -> None:
    from fae.pipecat.summarizer_bridge import build_assistant_aggregator_params

    params = build_assistant_aggregator_params(
        enabled=True,
        max_context_tokens=6000,
        max_unsummarized_messages=30,
        target_context_tokens=2000,
        min_messages_after_summary=2,
    )
    assert params is not None
    assert params.enable_auto_context_summarization is True
    cfg = params.auto_context_summarization_config
    assert cfg is not None
    assert cfg.max_context_tokens == 6000
    assert cfg.max_unsummarized_messages == 30
    assert cfg.summary_config.target_context_tokens == 2000
    assert cfg.summary_config.min_messages_after_summary == 2


def test_builder_adjusts_oversized_target() -> None:
    """target_context_tokens > max_context_tokens auto-shrinks to 80%."""
    from fae.pipecat.summarizer_bridge import build_assistant_aggregator_params

    params = build_assistant_aggregator_params(
        enabled=True,
        max_context_tokens=1000,
        target_context_tokens=9000,
        min_messages_after_summary=2,
    )
    assert params is not None
    cfg = params.auto_context_summarization_config
    assert cfg is not None
    # Pipecat auto-adjusts to 80% of max_context_tokens when target exceeds it.
    assert cfg.summary_config.target_context_tokens == 800


def test_builder_message_only_trigger() -> None:
    """Token threshold off, message threshold on — supported via None."""
    from fae.pipecat.summarizer_bridge import build_assistant_aggregator_params

    params = build_assistant_aggregator_params(
        enabled=True,
        max_context_tokens=None,
        max_unsummarized_messages=12,
        target_context_tokens=1500,
        min_messages_after_summary=2,
    )
    assert params is not None
    cfg = params.auto_context_summarization_config
    assert cfg is not None
    assert cfg.max_context_tokens is None
    assert cfg.max_unsummarized_messages == 12