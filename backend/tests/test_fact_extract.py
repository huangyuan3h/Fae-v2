"""Tests for heuristic name extraction."""

from __future__ import annotations

from fae.memory.fact_extract import extract_display_name, facts_from_turn


def test_extract_chinese_name() -> None:
    assert extract_display_name("我叫小明") == "小明"
    assert extract_display_name("我的名字是张三。") == "张三"


def test_extract_english_name() -> None:
    assert extract_display_name("My name is Alice") == "Alice"


def test_facts_from_turn_builds_profile() -> None:
    profile, facts = facts_from_turn(user_text="我叫小明", session_id="s1")
    assert profile is not None
    assert profile.display_name == "小明"
    assert len(facts) == 1
    assert "小明" in facts[0].content


def test_no_name_no_facts() -> None:
    profile, facts = facts_from_turn(user_text="今天天气怎么样")
    assert profile is None
    assert facts == []
