"""Tests for Open-Meteo weather tool + profile helpers."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.skills_runtime import SkillActivationInfo
from fae.llm.client import LLMClient
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig, ToolCall
from fae.memory.fact_extract import extract_city, facts_from_turn
from fae.memory.profile_block import merge_human_profile, parse_human_profile
from fae.tools.context import build_context_block
from fae.tools.weather import (
    dispatch_weather_tool,
    fetch_weather,
    weather_likely,
)


def _weather_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "geocoding-api.open-meteo.com" in url:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Beijing",
                        "country": "China",
                        "admin1": "Beijing",
                        "latitude": 39.9,
                        "longitude": 116.4,
                        "timezone": "Asia/Shanghai",
                    }
                ]
            },
        )
    if "api.open-meteo.com" in url:
        return httpx.Response(
            200,
            json={
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-07-19T10:00",
                    "temperature_2m": 28.5,
                    "apparent_temperature": 30.0,
                    "relative_humidity_2m": 60,
                    "weather_code": 2,
                    "wind_speed_10m": 12.0,
                    "precipitation": 0.0,
                },
                "daily": {
                    "weather_code": [2],
                    "temperature_2m_max": [32.0],
                    "temperature_2m_min": [22.0],
                    "precipitation_probability_max": [20],
                },
            },
        )
    return httpx.Response(404, json={"error": url})


@pytest.mark.asyncio
async def test_fetch_weather_mock() -> None:
    transport = httpx.MockTransport(_weather_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        data = await fetch_weather("北京", client=client)
    assert data["ok"] is True
    assert data["city"] == "Beijing"
    assert data["current"]["temperature"] == 28.5
    assert "Partly cloudy" in data["current"]["condition"]


@pytest.mark.asyncio
async def test_dispatch_uses_default_city() -> None:
    transport = httpx.MockTransport(_weather_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        raw = await dispatch_weather_tool(
            "get_weather",
            "{}",
            default_city="北京",
            client=client,
        )
    payload = json.loads(raw)
    assert payload["ok"] is True


@pytest.mark.asyncio
async def test_dispatch_city_required() -> None:
    raw = await dispatch_weather_tool("get_weather", "{}")
    assert json.loads(raw)["error"] == "city_required"


def test_weather_likely() -> None:
    assert weather_likely("今天的天气怎么样")
    assert weather_likely("Do I need an umbrella?")
    assert not weather_likely("写一首诗")


def test_extract_city_and_facts() -> None:
    assert extract_city("我住在北京") == "北京"
    assert extract_city("I live in Tokyo") == "Tokyo"
    profile, facts = facts_from_turn(user_text="我住在上海")
    assert profile is not None
    assert profile.preferences.get("City") == "上海"
    assert any("Shanghai" in f.content or "上海" in f.content for f in facts)


def test_parse_and_merge_profile() -> None:
    text = merge_human_profile(
        "Name: 小明",
        preferences={"City": "北京", "Timezone": "Asia/Shanghai"},
    )
    parsed = parse_human_profile(text)
    assert parsed.display_name == "小明"
    assert parsed.city == "北京"
    assert parsed.timezone == "Asia/Shanghai"
    assert "Lives in 北京." in text
    # Update city without clobbering name
    text2 = merge_human_profile(text, preferences={"City": "上海"})
    parsed2 = parse_human_profile(text2)
    assert parsed2.display_name == "小明"
    assert parsed2.city == "上海"
    assert text2.count("Lives in") == 1


def test_build_context_includes_city() -> None:
    block = build_context_block(
        human_block="Name: A\nLives in 北京.\nTimezone: Asia/Shanghai"
    )
    assert "Home city (from human memory): 北京" in block
    assert "get_weather" in block
    assert "<fae_context>" in block


class _FakeProvider:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat(self, request: ChatRequest):  # noqa: ANN201
        from fae.llm.types import ChatResponse

        return ChatResponse(
            content="",
            model=request.config.model,
            tool_calls=[
                ToolCall(id="1", name="get_weather", arguments='{"city":"北京"}')
            ],
        )

    async def stream(self, request: ChatRequest):  # noqa: ANN201
        self.stream_calls += 1
        assert any(
            "tool_result" in m.content for m in request.messages if m.role == "system"
        )
        yield "今天北京多云，28度。"


@pytest.mark.asyncio
async def test_fetch_city_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding" in str(request.url):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        data = await fetch_weather("Nowhereville", client=client)
    assert data["ok"] is False
    assert data["error"] == "city_not_found"


@pytest.mark.asyncio
async def test_resolve_location_defaults(tmp_path: Path) -> None:
    from fae.memory.embedded import EmbeddedMemoryClient
    from fae.pipecat.services.letta_memory import LettaMemoryService
    from fae.tools.context import resolve_location_defaults

    client = EmbeddedMemoryClient(tmp_path / "m.db")
    await client.ensure_agent()
    await client.update_user(
        __import__("fae.memory.schemas", fromlist=["UserProfile"]).UserProfile(
            display_name="A",
            preferences={"City": "杭州", "Timezone": "Asia/Shanghai"},
        )
    )
    memory = LettaMemoryService(client)
    city, tz = await resolve_location_defaults(memory)
    assert city == "杭州"
    assert tz == "Asia/Shanghai"
    city2, tz2 = await resolve_location_defaults(
        memory, env_city="深圳", env_timezone="Asia/Hong_Kong"
    )
    assert city2 == "深圳"
    assert tz2 == "Asia/Hong_Kong"
    await client.close()


@pytest.mark.asyncio
async def test_llm_turn_injects_weather_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_dispatch(name, arguments, *, default_city=None, client=None):
        return json.dumps(
            {"ok": True, "city": "Beijing", "current": {"temperature": 28}}
        )

    monkeypatch.setattr(
        "fae.agent.llm_turn.dispatch_weather_tool",
        _fake_dispatch,
    )
    provider = _FakeProvider()
    client = LLMClient(provider)
    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="今天天气怎么样")],
    )
    new_req, _act, early = await apply_lazy_skill_tool(
        client,
        req,
        SkillActivationInfo(),
        None,
        weather_enabled=True,
        default_city="北京",
    )
    assert early is None
    assert any("tool_result" in m.content for m in new_req.messages if m.role == "system")
