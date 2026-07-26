"""Tests for the persistent + in-memory ``ApprovalStore``.

Coverage targets:

- State machine: pending → approved / denied / expired / cancelled.
- Idempotency of repeated decisions and resolving an already-finalized row.
- ``sweep_expired`` reaps TTL-lapsed rows AND resolves their futures.
- ``mark_consumed`` flips ``consumed=1`` for audit.
- ``has_active_session_rule`` honours the 1h freshness window.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from fae.approvals import (
    STATUS_APPROVED,
    STATUS_AWAITING_CONFIRM,
    STATUS_CANCELLED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    VALID_ACTIONS,
    ApprovalRequest,
    ApprovalStore,
    request_approval,
)


def _store(tmp_path: Path) -> ApprovalStore:
    return ApprovalStore(tmp_path / "approvals.db")


def _request(
    *,
    store: ApprovalStore,
    tool: str = "write_file",
    args: str | None = None,
    approval_id: str | None = None,
    args_hash: str = "hash",
) -> ApprovalRequest:
    now = time.time()
    if args is None:
        args = json.dumps({"path": "x", "content": "y"})
    return ApprovalRequest(
        id=approval_id or store._next_id(),
        session_id="s1",
        turn_id="t1",
        channel="ws",
        channel_id=None,
        tool_name=tool,
        risk_tier="sensitive",
        arguments=args[:2000],
        arguments_summary=args[:1500],
        arguments_full=args,
        diff_preview="edit",
        requester="agent",
        status=STATUS_PENDING,
        decision_reason=None,
        decided_by=None,
        needs_double_confirm=False,
        double_confirm_window_s=5.0,
        args_hash=args_hash,
        ttl_s=60.0,
        created_at=now,
        expires_at=now + 60.0,
        decided_at=None,
        consumed=False,
    )


def test_create_and_get(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    store.create(req)
    loaded = store.get(req.id)
    assert loaded is not None
    assert loaded.status == STATUS_PENDING


def test_resolve_approve_denied_cancel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for action, expected in (
        ("approve", STATUS_APPROVED),
        ("deny", STATUS_DENIED),
        ("cancel", STATUS_CANCELLED),
    ):
        req = _request(store=store, tool=f"run_bash_{action}")
        store.create(req)
        updated = store.resolve(
            req.id, action=action, reason="x", decided_by="user"
        )
        assert updated.status == expected


def test_resolve_double_confirm_flow(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store, tool="schedule_create_job")
    object.__setattr__(req, "needs_double_confirm", True)
    store.create(req)
    pending = store.resolve(req.id, action="approve", decided_by="user")
    assert pending.status == STATUS_AWAITING_CONFIRM
    confirmed = store.resolve(req.id, action="approve", decided_by="user", confirm=True)
    assert confirmed.status == STATUS_APPROVED


def test_resolve_idempotent_for_terminal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    store.create(req)
    store.resolve(req.id, action="deny", decided_by="user")
    again = store.resolve(req.id, action="approve", decided_by="user")
    # Terminal rows ignore new decisions (status stays denied).
    assert again.status == STATUS_DENIED


def test_resolve_invalid_action_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    store.create(req)
    with pytest.raises(ValueError):
        store.resolve(req.id, action="bogus")


def test_sweep_expired_marks_lapsed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    object.__setattr__(req, "expires_at", time.time() - 1)
    store.create(req)
    swept = store.sweep_expired()
    assert len(swept) == 1
    assert swept[0].status == STATUS_EXPIRED


def test_mark_consumed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    store.create(req)
    store.resolve(req.id, action="approve", decided_by="user")
    consumed = store.mark_consumed(req.id)
    assert consumed.consumed is True
    assert consumed.status == STATUS_APPROVED


def test_list_filters(tmp_path: Path) -> None:
    store = _store(tmp_path)
    wf = _request(store=store, tool="write_file")
    rb = _request(store=store, tool="run_bash")
    store.create(wf)
    store.create(rb)
    items = store.list_requests(tool_name="write_file")
    assert len(items) == 1
    assert items[0].tool_name == "write_file"


def test_has_active_session_rule(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _request(store=store)
    store.create(req)
    store.resolve(req.id, action="approve", decided_by="user")
    store.mark_consumed(req.id)
    assert store.has_active_session_rule("s1", "hash", as_of=time.time())
    # Wrong args_hash → no rule.
    assert not store.has_active_session_rule("s1", "different", as_of=time.time())
    # Different session → no rule.
    assert not store.has_active_session_rule("other", "hash", as_of=time.time())


def _drive_request(store: ApprovalStore, args: str) -> asyncio.Task:
    async def _run() -> ApprovalRequest:
        return await request_approval(
            store,
            tool_name="write_file",
            arguments=args,
            session_id="s1",
            turn_id="t1",
            channel="ws",
            channel_id=None,
            requester="agent",
            ttl_s=2.0,
        )

    return asyncio.create_task(_run())


@pytest.mark.asyncio
async def test_request_approval_approved_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    args = json.dumps({"path": "x", "content": "y"})
    task = _drive_request(store, args)
    # Let the request create the row + register future.
    await asyncio.sleep(0.05)
    pending = store.list_requests(session_id="s1", status=STATUS_PENDING)
    assert pending and len(pending) == 1
    approval_id = pending[0].id
    store.resolve(approval_id, action="approve", decided_by="user")
    result = await asyncio.wait_for(task, timeout=2)
    assert result.status == STATUS_APPROVED


@pytest.mark.asyncio
async def test_request_approval_timeout_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    args = json.dumps({"path": "x", "content": "y"})

    async def _run() -> ApprovalRequest:
        return await request_approval(
            store,
            tool_name="edit_file",
            arguments=args,
            session_id="s1",
            turn_id=None,
            channel="ws",
            channel_id=None,
            requester="agent",
            ttl_s=0.2,
        )

    task = asyncio.create_task(_run())
    res = await asyncio.wait_for(task, timeout=2)
    assert res.status == STATUS_EXPIRED


@pytest.mark.asyncio
async def test_request_approval_denied_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    args = json.dumps({"path": "x"})

    async def _run() -> ApprovalRequest:
        return await request_approval(
            store,
            tool_name="run_bash",
            arguments=args,
            session_id="s1",
            turn_id=None,
            channel="ws",
            channel_id=None,
            requester="agent",
            ttl_s=2.0,
        )

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.05)
    pending = store.list_requests(session_id="s1", status=STATUS_PENDING)
    assert pending
    store.resolve(pending[0].id, action="deny", reason="nope", decided_by="user")
    res = await asyncio.wait_for(task, timeout=2)
    assert res.status == STATUS_DENIED
    assert res.decision_reason == "nope"


def test_valid_actions_constant() -> None:
    assert set(VALID_ACTIONS) == {"approve", "deny", "cancel"}
