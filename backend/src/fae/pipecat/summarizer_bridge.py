"""Builder helpers for Pipecat LLMAssistantAggregatorParams.

R3 of doc/design/CONTEXT_ENGINEERING.md: enable ``LLMContextSummarizer`` on the
Daily voice path so long phone calls don't blow past the model window.

We keep the summarizer *off* by default — it adds a second LLM call per
trigger and the memory compactor / R2 summarizer already cover the
default browser chat path. The Daily path is the only one where voice
utterances can accumulate fast enough to matter, so the flag lives on
the Daily settings block.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMAssistantAggregatorParams,
    )


def build_assistant_aggregator_params(
    *,
    enabled: bool,
    max_context_tokens: int | None = 8000,
    max_unsummarized_messages: int | None = 20,
    target_context_tokens: int = 4000,
    min_messages_after_summary: int = 4,
    summary_llm: Any | None = None,
) -> "LLMAssistantAggregatorParams":
    """Return an LLMAssistantAggregatorParams with summarization wired in.

    The function is import-safe even when pipecat isn't installed (e.g.
    on a worker that only runs the browser WS path). In that case it
    returns ``None`` so callers can detect the missing dependency.
    """
    try:
        from pipecat.processors.aggregators.llm_response_universal import (
            LLMAssistantAggregatorParams,
        )
        from pipecat.utils.context.llm_context_summarization import (
            LLMAutoContextSummarizationConfig,
            LLMContextSummaryConfig,
        )
    except ImportError:  # pragma: no cover — pipecat not installed
        return None  # type: ignore[return-value]

    if not enabled:
        return LLMAssistantAggregatorParams(
            enable_auto_context_summarization=False,
        )

    summary_config = LLMContextSummaryConfig(
        target_context_tokens=target_context_tokens,
        min_messages_after_summary=min_messages_after_summary,
        llm=summary_llm,
    )
    auto_config = LLMAutoContextSummarizationConfig(
        max_context_tokens=max_context_tokens,
        max_unsummarized_messages=max_unsummarized_messages,
        summary_config=summary_config,
    )
    return LLMAssistantAggregatorParams(
        enable_auto_context_summarization=True,
        auto_context_summarization_config=auto_config,
    )