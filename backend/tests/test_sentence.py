"""Tests for SentenceAggregator."""

from __future__ import annotations

from fae.pipecat.sentence import SentenceAggregator


def test_aggregator_emits_on_chinese_period() -> None:
    agg = SentenceAggregator()
    assert agg.push("你") == []
    assert agg.push("好") == []
    assert agg.push("。") == ["你好。"]
    assert agg.buffer == ""


def test_aggregator_handles_multiple_sentences_in_one_push() -> None:
    agg = SentenceAggregator()
    out = agg.push("Hello. World!")
    assert out == ["Hello.", " World!"]
    assert agg.flush() is None


def test_aggregator_flush_returns_leftover() -> None:
    agg = SentenceAggregator()
    assert agg.push("unfinished") == []
    assert agg.flush() == "unfinished"
    assert agg.flush() is None
