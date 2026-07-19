"""Fixture-driven skill trigger quality (Phase Q.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fae.agent.skills_loader import SkillsLoader
from fae.agent.skills_matcher import match_trigger_skills
from fae.agent.skills_runtime import SkillRuntime

_FIXTURE = Path(__file__).parent / "fixtures" / "skill_trigger_cases.json"


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_skill_trigger_fixture(case: dict, tmp_path: Path) -> None:
    loader = SkillsLoader()
    matches = match_trigger_skills(case["text"], loader.list_skills())
    matched = {m.name for m in matches}

    rt = SkillRuntime(
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
        max_active=3,
    )
    active = set(rt.select(case["text"], session_id="t", record_trigger=False).active)

    for name in case.get("expect_active") or []:
        assert name in matched or name in active, (
            f"{case['id']}: expected {name} in matches={matched} active={active}"
        )
        assert name in active, f"{case['id']}: expected {name} active, got {active}"

    for name in case.get("expect_absent") or []:
        assert name not in active, f"{case['id']}: {name} should not activate"


def test_unknown_requires_tools_skips(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "broken.md").write_text(
        """---
name: broken_tool_skill
description: needs fake tool
triggers:
  - need_fake_tool_xyz
requires_tools:
  - search_history
priority: 9
load_strategy: trigger_based
---
body
""",
        encoding="utf-8",
    )
    rt = SkillRuntime(
        skills_dir=skills_dir,
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    act = rt.select("need_fake_tool_xyz please", session_id="s")
    assert "broken_tool_skill" not in act.active


def test_max_context_tokens_truncates(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    body = "WORD " * 500
    (skills_dir / "long.md").write_text(
        f"""---
name: long_skill
description: long
triggers:
  - longskilltriggerphrase
priority: 9
max_context_tokens: 100
load_strategy: trigger_based
---
{body}
""",
        encoding="utf-8",
    )
    rt = SkillRuntime(
        skills_dir=skills_dir,
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    from fae.llm.types import ChatMessage, ChatRequest, LLMConfig

    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="longskilltriggerphrase")],
    )
    prepared, act = rt.prepare_request(req, session_id="s")
    assert "long_skill" in act.active
    skill_msgs = [
        m.content for m in prepared.messages if m.role == "system" and "<active_skills>" in m.content
    ]
    assert skill_msgs
    assert "…" in skill_msgs[0]
    assert len(skill_msgs[0]) < len(body) + 200


def test_empty_seed_skips_trigger_skills(tmp_path: Path) -> None:
    rt = SkillRuntime(
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
    )
    act = rt.select("", session_id="daily", record_trigger=False)
    assert "technical_debugging" not in act.active
    assert "travel_planning" not in act.active
