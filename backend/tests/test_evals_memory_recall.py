"""Eval runner: evals/agent/memory-recall.json (Phase Q.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals_paths import evals_path
from fae.memory.schemas import FactIn
from memory_helpers import make_embedded

_CASES = json.loads(
    evals_path("agent", "memory-recall.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_eval_memory_recall(case: dict, tmp_path: Path) -> None:
    client, _recall, service = make_embedded(tmp_path, name=f"{case['id']}.db")
    await client.ensure_agent()
    setup = case.get("setup") or {}

    if setup.get("user_text"):
        await service.persist_turn(
            session_id="default",
            user_text=setup["user_text"],
            assistant_text=setup.get("assistant_text") or "ok",
        )
    for fact in setup.get("facts") or []:
        await client.save_fact(
            FactIn(
                content=fact["content"],
                tags=list(fact.get("tags") or []),
                session_id="default",
            )
        )

    prompt = await client.recall_for_prompt(
        case["query"], session_id="default", recent_limit=8
    )
    for needle in case.get("expect_substrings") or []:
        assert needle in prompt, (
            f"{case['id']}: expected {needle!r} in recall prompt:\n{prompt[:800]}"
        )
    await client.close()
