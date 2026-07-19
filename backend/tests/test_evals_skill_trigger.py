"""Eval runner: evals/agent/skill-trigger.json (Phase Q.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals_paths import evals_path
from fae.agent.skills_runtime import SkillRuntime

_CASES = json.loads(
    evals_path("agent", "skill-trigger.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_eval_skill_trigger(case: dict, tmp_path: Path) -> None:
    assert evals_path("agent", "skill-trigger.json").is_file()
    rt = SkillRuntime(
        state_path=tmp_path / "state.json",
        repo_root=tmp_path,
        max_active=3,
    )
    active = set(
        rt.select(case["text"], session_id="eval", record_trigger=False).active
    )
    for name in case.get("expect_active") or []:
        assert name in active, f"{case['id']}: expected {name} in {active}"
    for name in case.get("expect_absent") or []:
        assert name not in active, f"{case['id']}: {name} should not activate"
