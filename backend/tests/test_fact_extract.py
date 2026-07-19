"""Tests for heuristic name / city extraction."""

from __future__ import annotations

from fae.memory.fact_extract import (
    extract_city,
    extract_display_name,
    extract_timezone,
    facts_from_turn,
)


def test_extract_chinese_name() -> None:
    assert extract_display_name("我叫小明") == "小明"
    assert extract_display_name("我的名字是张三。") == "张三"


def test_extract_english_name() -> None:
    assert extract_display_name("My name is Alice") == "Alice"


def test_extract_city_and_timezone() -> None:
    assert extract_city("我住在北京") == "北京"
    assert extract_city("I live in Tokyo") == "Tokyo"
    assert extract_timezone("时区是 Asia/Shanghai") == "Asia/Shanghai"
    assert extract_timezone("timezone is America/New_York") == "America/New_York"


def test_facts_from_turn_builds_profile() -> None:
    profile, facts = facts_from_turn(user_text="我叫小明", session_id="s1")
    assert profile is not None
    assert profile.display_name == "小明"
    assert len(facts) == 1
    assert "小明" in facts[0].content


def test_facts_from_turn_city() -> None:
    profile, facts = facts_from_turn(user_text="我住在杭州")
    assert profile is not None
    assert profile.preferences["City"] == "杭州"
    assert any("杭州" in f.content for f in facts)


def test_no_name_no_facts() -> None:
    profile, facts = facts_from_turn(user_text="今天天气怎么样")
    assert profile is None
    assert facts == []
