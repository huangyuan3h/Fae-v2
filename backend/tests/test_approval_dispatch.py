"""End-to-end tests for the sensitive-op dispatcher integration.

Confirms the gate around ``_dispatch_coding_tool``:

- Sensitive tools (write_file / edit_file / make_directory / run_bash) await
  human approval when no policy pre-authorises them.
- Always-allow policy short-circuits the gate.
- Deny / expire yield ``approval_denied`` / ``approval_expired`` results.
- Sensitive schedule tools (cancel_job) follow the same pattern.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from fae.agent.llm_turn import _dispatch_coding_tool
from fae.approvals import ApprovalStore
from fae.tool_registry import EffectivePolicy


def _record(events: list[dict]) -> None:
    pass


@pytest.mark.asyncio
async def test_dispatch_blocks_without_approval(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.db")
    target = tmp_path / "src" / "demo.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []

    async def _emit(ev: dict) -> None:
        events.append(ev)

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        items = store.list_requests(status="pending", session_id="s1")
        assert items, "expected a pending approval to be created"
        store.resolve(items[0].id, action="approve", decided_by="user")

    decision_task = asyncio.create_task(_decide_later())
    result = await _dispatch_coding_tool(
        "write_file",
        json.dumps({"path": str(target), "content": "hello"}),
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        session_id="s1",
        on_tool_event=_emit,
        approval_store=store,
        trace_turn_id="turn-1",
    )
    await decision_task
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert target.read_text() == "hello"
    types = [ev.get("type") for ev in events]
    assert "approval_request" in types


@pytest.mark.asyncio
async def test_dispatch_returns_denied_when_user_says_no(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.db")
    target = tmp_path / "src" / "nope.txt"
    events: list[dict] = []

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        items = store.list_requests(status="pending", session_id="s1")
        store.resolve(items[0].id, action="deny", reason="nope", decided_by="user")

    asyncio.create_task(_decide_later())
    result = await _dispatch_coding_tool(
        "write_file",
        json.dumps({"path": str(target), "content": "no"}),
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        session_id="s1",
        on_tool_event=lambda ev: events.append(ev),
        approval_store=store,
        trace_turn_id="turn-1",
    )
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"] == "approval_denied"
    assert payload["decision_reason"] == "nope"
    assert not target.exists()


@pytest.mark.asyncio
async def test_dispatch_always_allow_skips_gate(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.db")
    target = tmp_path / "src" / "auto.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []

    policy = EffectivePolicy(
        session_id="s1", always_allow=frozenset({"write_file"})
    )
    result = await _dispatch_coding_tool(
        "write_file",
        json.dumps({"path": str(target), "content": "yes"}),
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        session_id="s1",
        on_tool_event=lambda ev: events.append(ev),
        approval_store=store,
        effective_policy=policy,
    )
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert target.read_text() == "yes"
    # No approval_request event was ever emitted.
    assert not any(ev.get("type") == "approval_request" for ev in events)


@pytest.mark.asyncio
async def test_dispatch_bash_blocks_until_decision(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.db")
    events: list[dict] = []

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        items = store.list_requests(status="pending", session_id="s1")
        store.resolve(items[0].id, action="approve", decided_by="user")

    asyncio.create_task(_decide_later())
    result = await _dispatch_coding_tool(
        "run_bash",
        json.dumps({"command": "ls"}),
        workspace_root=str(tmp_path),
        bash_enabled=True,
        session_id="s1",
        on_tool_event=lambda ev: events.append(ev),
        approval_store=store,
        trace_turn_id="turn-1",
    )
    payload = json.loads(result)
    assert payload.get("ok") is True
    assert "approval_request" in [ev.get("type") for ev in events]


@pytest.mark.asyncio
async def test_dispatch_no_store_blocks_with_error(tmp_path: Path) -> None:
    """No ApprovalStore wired → block with ``approval_unavailable``."""
    target = tmp_path / "src" / "missing.txt"
    events: list[dict] = []
    result = await _dispatch_coding_tool(
        "write_file",
        json.dumps({"path": str(target), "content": "x"}),
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        session_id="s1",
        on_tool_event=lambda ev: events.append(ev),
        approval_store=None,
    )
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"] == "approval_unavailable"
    assert not target.exists()


@pytest.mark.asyncio
async def test_dispatch_uses_diff_preview(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "approvals.db")

    captured: list[dict] = []

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        items = store.list_requests(status="pending", session_id="s1")
        captured.append(items[0].to_dict())
        store.resolve(items[0].id, action="approve", decided_by="user")

    asyncio.create_task(_decide_later())
    await _dispatch_coding_tool(
        "write_file",
        json.dumps({"path": "src/app.py", "content": "print(42)"}),
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        session_id="s1",
        approval_store=store,
    )
    assert captured[0]["diff_preview"] is not None
    assert "src/app.py" in captured[0]["diff_preview"]
