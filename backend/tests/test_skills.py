"""Phase 3 skills: loader, matcher, runtime, API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_loader import SkillsLoader, parse_skill_markdown
from fae.agent.skills_matcher import match_trigger_skills, score_skill
from fae.agent.skills_runtime import SkillRuntime
from fae.agent.skills_schema import LoadStrategy
from fae.api import create_app
from fae.llm import ChatMessage, ChatRequest, FakeProvider, LLMClient, LLMConfig, ToolCall
from fae.llm.types import ChatResponse


SAMPLE = """---
name: sample_skill
description: demo
triggers:
  - hello world
priority: 5
load_strategy: trigger_based
---

# Body
Do the thing.
"""


def test_parse_skill_markdown_ok() -> None:
    skill = parse_skill_markdown(SAMPLE)
    assert skill.meta.name == "sample_skill"
    assert skill.meta.load_strategy == LoadStrategy.TRIGGER_BASED
    assert "Do the thing" in skill.body


def test_parse_missing_frontmatter() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skill_markdown("# no meta\n")


def test_parse_bad_yaml() -> None:
    with pytest.raises(ValueError, match="YAML|invalid"):
        parse_skill_markdown("---\n[unterminated\n---\nbody\n")


def test_loader_lists_builtin_skills() -> None:
    loader = SkillsLoader()
    names = {s.meta.name for s in loader.list_skills()}
    assert "technical_debugging" in names
    assert "proactive_outreach" in names
    assert len(names) >= 6


def test_stack_trace_matches_technical_debugging() -> None:
    loader = SkillsLoader()
    skills = loader.list_skills()
    text = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 10, in <module>\n'
        "TypeError: 'NoneType' object is not subscriptable"
    )
    matches = match_trigger_skills(text, skills)
    assert matches
    assert matches[0].name == "technical_debugging"
    assert matches[0].score >= 0.9


def test_cooldown_blocks_retrigger(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "technical_debugging.md").write_text(
        """---
name: technical_debugging
description: dbg
triggers:
  - Traceback
priority: 9
cooldown_seconds: 3600
load_strategy: trigger_based
---
body
""",
        encoding="utf-8",
    )
    rt = SkillRuntime(
        skills_dir=skills_dir,
        state_path=tmp_path / "state.json",
        max_active=2,
        repo_root=tmp_path,
    )
    text = "Traceback (most recent call last): boom"
    first = rt.select(text, session_id="s1")
    assert "technical_debugging" in first.active
    second = rt.select(text, session_id="s1")
    assert "technical_debugging" not in second.active


@pytest.mark.asyncio
async def test_prepare_injects_active_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "technical_debugging.md").write_text(
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("src/skills/technical_debugging.md")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rt = SkillRuntime(
        skills_dir=skills_dir,
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[
            ChatMessage(
                role="user",
                content="Traceback (most recent call last):\nError: x",
            )
        ],
    )
    prepared, activation = await prepare_chat_request(
        req, session_id="s", memory=None, skills=rt
    )
    assert "technical_debugging" in activation.active
    assert any(
        m.role == "system" and "<active_skills>" in m.content
        for m in prepared.messages
    )


@pytest.mark.asyncio
async def test_lazy_request_skill_tool(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "proactive_outreach.md").write_text(
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("src/skills/proactive_outreach.md")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rt = SkillRuntime(
        skills_dir=skills_dir,
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    provider = FakeProvider(
        responses=["ok after skill"],
        tool_call_responses=[
            [
                ToolCall(
                    id="1",
                    name="request_skill",
                    arguments='{"name":"proactive_outreach"}',
                )
            ]
        ],
    )
    client = LLMClient(provider)
    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="hi")],
    )
    prepared, activation = rt.prepare_request(req, session_id="s")
    assert activation.tools
    new_req, new_act, early = await apply_lazy_skill_tool(
        client, prepared, activation, rt
    )
    assert early is None
    assert "proactive_outreach" in new_act.active
    assert any("proactive_outreach" in m.content for m in new_req.messages if m.role == "system")


def test_skills_api_list_and_test_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LETTA_MODE", "off")
    monkeypatch.setenv("SLEEPTIME_ENABLED", "false")
    monkeypatch.setenv("SKILLS_ENABLED", "true")
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()}
    assert "technical_debugging" in names

    trig = client.post(
        "/api/skills/test-trigger",
        json={
            "text": "Traceback (most recent call last):\n  File \"x.py\"\nTypeError: z"
        },
    )
    assert trig.status_code == 200
    body = trig.json()
    assert "technical_debugging" in body["active"]


def test_skills_api_patch_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LETTA_MODE", "off")
    monkeypatch.setenv("SLEEPTIME_ENABLED", "false")
    monkeypatch.setenv("SKILLS_ENABLED", "true")
    monkeypatch.setenv("SKILLS_STATE_PATH", str(tmp_path / "state.json"))
    from fae import config as config_module

    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.patch(
        "/api/skills/technical_debugging",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    # restore
    client.patch("/api/skills/technical_debugging", json={"enabled": True})


def test_score_skill_empty() -> None:
    skill = parse_skill_markdown(SAMPLE)
    assert score_skill("", skill) == 0.0
