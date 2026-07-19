"""Tests for heuristic name / city extraction and corrections."""

from __future__ import annotations

from fae.memory.fact_extract import (
    extract_city,
    extract_display_name,
    extract_timezone,
    facts_from_turn,
)
from fae.memory.profile_block import parse_human_profile, upsert_location_note


def test_extract_chinese_name() -> None:
    assert extract_display_name("我叫小明") == "小明"
    assert extract_display_name("我的名字是张三。") == "张三"


def test_extract_english_name() -> None:
    assert extract_display_name("My name is Alice") == "Alice"


def test_extract_city_and_timezone() -> None:
    assert extract_city("我住在北京") == "北京"
    assert extract_city("I live in Tokyo") == "Tokyo"
    assert extract_city("我搬到了杭州") == "杭州"
    assert extract_timezone("时区是 Asia/Shanghai") == "Asia/Shanghai"
    assert extract_timezone("timezone is America/New_York") == "America/New_York"


def test_extract_city_correction() -> None:
    assert extract_city("不对，是上海") == "上海"
    assert extract_city("不是北京是杭州") == "杭州"
    assert extract_city("改成深圳") == "深圳"
    assert extract_city("actually Shanghai") == "Shanghai"


def test_extract_city_after_assistant_ask() -> None:
    ask = "你在哪个城市？我说了会记住。"
    assert extract_city("上海", assistant_text=ask) == "上海"
    assert extract_city("Beijing", assistant_text="Which city do you live in?") == "Beijing"
    # Without a prior ask, bare city should not be extracted
    assert extract_city("上海") is None


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


def test_upsert_and_parse_freeform_location() -> None:
    text = upsert_location_note("Unknown user. Ask once…", "北京")
    assert "Lives in 北京." in text
    assert "Unknown user" not in text
    parsed = parse_human_profile(text)
    assert parsed.city == "北京"
    text2 = upsert_location_note(text, "上海")
    assert text2.count("Lives in") == 1
    assert parse_human_profile(text2).city == "上海"
