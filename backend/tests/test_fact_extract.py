"""Tests for heuristic name / city / dietary extraction and corrections."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.memory.fact_extract import (
    extract_city,
    extract_dietary,
    extract_display_name,
    extract_timezone,
    facts_from_turn,
)
from fae.memory.profile_block import (
    parse_human_profile,
    upsert_dietary_note,
    upsert_location_note,
)
from memory_helpers import make_embedded


def test_extract_chinese_name() -> None:
    assert extract_display_name("我叫小明") == "小明"
    assert extract_display_name("我的名字是张三。") == "张三"
    assert extract_display_name("叫我阿明") == "阿明"
    assert extract_display_name("我是李雷") == "李雷"
    assert extract_display_name("我是一个程序员") is None


def test_extract_english_name() -> None:
    assert extract_display_name("My name is Alice") == "Alice"
    assert extract_display_name("Call me Bob") == "Bob"


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


def test_extract_dietary() -> None:
    assert extract_dietary("我忌香菜") == "香菜"
    assert extract_dietary("不能吃花生") == "花生"
    assert extract_dietary("对海鲜过敏") == "海鲜"
    assert extract_dietary("I can't eat nuts") == "nuts"
    assert extract_dietary("今天天气怎么样") is None


def test_facts_from_turn_name_city_dietary() -> None:
    profile, facts = facts_from_turn(
        user_text="我叫小明，住在北京，忌香菜",
        session_id="default",
    )
    assert profile is not None
    assert profile.display_name == "小明"
    assert profile.preferences["City"] == "北京"
    assert profile.preferences["Avoids"] == "香菜"
    tags = {t for f in facts for t in f.tags}
    assert "identity" in tags
    assert "dietary" in tags


def test_upsert_dietary_note() -> None:
    text = upsert_dietary_note("Name: 小明", "香菜")
    assert "Avoids: 香菜." in text
    text2 = upsert_dietary_note(text, "花生")
    assert text2.count("Avoids:") == 1
    assert "花生" in text2


@pytest.mark.asyncio
async def test_persist_identity_survives_recall(tmp_path: Path) -> None:
    """MQ-3: name/city/dietary land in human and show up after 'new session'."""
    client, _recall, service = make_embedded(tmp_path, name="id.db")
    await client.ensure_agent()
    await service.persist_turn(
        session_id="default",
        user_text="我叫小明，住在北京，忌香菜",
        assistant_text="好的，记住了。",
    )
    human = await client.get_block("human")
    assert "小明" in human
    assert "北京" in human
    assert "香菜" in human

    # Simulate refresh: same stable session id, empty recent is fine — human is global.
    prompt = await client.recall_for_prompt("我叫什么", session_id="default")
    assert "[human]" in prompt
    assert "小明" in prompt
    assert "北京" in prompt
    assert "香菜" in prompt
    await client.close()
