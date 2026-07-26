"""Tests for /api/memory/stats cache-health + context-engineering flags."""

from __future__ import annotations

from fae.api.memory import _cache_health, _feat_flag, _cache_control_state


def test_cache_health_unknown_when_no_usage() -> None:
    h = _cache_health(None, {})
    assert h["status"] == "unknown"
    assert h["ratio"] is None
    assert "no usage" in h["signal"]


def test_cache_health_ok_when_high_ratio() -> None:
    h = _cache_health(0.7, {"prompt_tokens": 1000, "cached_tokens": 700})
    assert h["status"] == "ok"
    assert h["ratio"] == 0.7
    assert "paying off" in h["signal"]


def test_cache_health_warn_when_low_ratio() -> None:
    h = _cache_health(0.05, {"prompt_tokens": 1000, "cached_tokens": 50})
    assert h["status"] == "warn"
    assert h["ratio"] == 0.05
    assert "churning" in h["signal"]


def test_cache_health_warn_when_moderate_ratio() -> None:
    h = _cache_health(0.3, {"prompt_tokens": 1000, "cached_tokens": 300})
    assert h["status"] == "warn"
    assert h["ratio"] == 0.3


def test_feat_flag_reads_settings() -> None:
    class _S:
        foo_enabled = True
        bar_enabled = False

    assert _feat_flag(_S(), "foo_enabled") == "on"
    assert _feat_flag(_S(), "bar_enabled") == "off"
    assert _feat_flag(None, "x") == "unknown"


def test_cache_control_state_inference() -> None:
    assert _cache_control_state(None) == "unknown"
    class _S:
        pass

    assert _cache_control_state(_S()) == "auto_or_anthropic"