"""Phase 4 scaffold: activity tracker, outreach policy, job specs, activate()."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.agent.skills_runtime import SkillRuntime
from fae.llm import ChatMessage, ChatRequest, LLMConfig
from fae.scheduler import ActivityTracker, OutreachPolicy, should_outreach
from fae.scheduler.heartbeat import HeartbeatLoop
from fae.scheduler.jobs import builtin_job_specs, list_job_ids


def test_activity_tracker_idle() -> None:
    at = ActivityTracker()
    assert at.idle_seconds("s1") is None
    at.touch("s1", at=1000.0)
    assert at.last_at("s1") == 1000.0
    assert at.idle_seconds("s1", now=1060.0) == 60.0
    assert at.sessions() == ["s1"]


def test_should_outreach_rules() -> None:
    policy = OutreachPolicy(idle_seconds=100, cooldown_seconds=50, max_per_day=1)
    assert not should_outreach(
        idle_seconds=200,
        seconds_since_last_outreach=None,
        outreach_count_today=0,
        has_open_topic=False,
        policy=policy,
    )
    assert not should_outreach(
        idle_seconds=10,
        seconds_since_last_outreach=None,
        outreach_count_today=0,
        has_open_topic=True,
        policy=policy,
    )
    assert should_outreach(
        idle_seconds=200,
        seconds_since_last_outreach=None,
        outreach_count_today=0,
        has_open_topic=True,
        policy=policy,
    )
    assert not should_outreach(
        idle_seconds=200,
        seconds_since_last_outreach=10,
        outreach_count_today=0,
        has_open_topic=True,
        policy=policy,
    )
    assert not should_outreach(
        idle_seconds=200,
        seconds_since_last_outreach=None,
        outreach_count_today=1,
        has_open_topic=True,
        policy=policy,
    )


@pytest.mark.asyncio
async def test_heartbeat_tick_fires_once() -> None:
    at = ActivityTracker()
    at.touch("s1", at=0.0)
    fired: list[str] = []

    async def on_outreach(sid: str) -> None:
        fired.append(sid)

    loop = HeartbeatLoop(
        at,
        policy=OutreachPolicy(idle_seconds=10, cooldown_seconds=100, max_per_day=1),
        on_outreach=on_outreach,
        open_topic_checker=lambda _sid: True,
    )
    out = await loop.tick(now=100.0)
    assert out == ["s1"]
    assert fired == ["s1"]
    # same day + cooldown → no second fire
    out2 = await loop.tick(now=150.0)
    assert out2 == []


def test_builtin_jobs() -> None:
    from fae.scheduler.jobs import JobSpec

    specs = builtin_job_specs()
    assert {s.id for s in specs} >= {"daily_checkin", "weekly_recap"}
    assert "daily_checkin" in list_job_ids()
    assert "custom" in list_job_ids([JobSpec(id="custom", kind="date")])


def test_activate_force_loads_lazy_skill(tmp_path: Path) -> None:
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
    info = rt.activate(["proactive_outreach"], session_id="proactive")
    assert "proactive_outreach" in info.active
    # cooldown (12h) blocks immediate re-activate
    again = rt.activate(["proactive_outreach"], session_id="proactive")
    assert again.active == []
    # bypass for ops / tests
    forced = rt.activate(
        ["proactive_outreach"],
        session_id="proactive",
        respect_cooldown=False,
    )
    assert "proactive_outreach" in forced.active

    req = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="ping")],
    )
    prepared, act = rt.prepare_activated_request(
        req,
        ["proactive_outreach"],
        session_id="other",
        respect_cooldown=False,
    )
    assert "proactive_outreach" in act.active
    assert any(
        m.role == "system" and "<active_skills>" in m.content for m in prepared.messages
    )
