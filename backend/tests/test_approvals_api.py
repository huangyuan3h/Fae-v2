"""Integration tests for ``/api/approvals`` + session policies."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.approvals import (
    STATUS_PENDING,
    ApprovalRequest,
    ApprovalStore,
)


def _build_app(tmp_path: Path) -> tuple:
    app = create_app()
    from fae.sessions import SessionStore

    store = ApprovalStore(tmp_path / "approvals.db")
    sessions = SessionStore()
    session = sessions.create()
    app.state.approvals = store
    app.state.sessions = sessions
    return app, store, session, sessions


def _make_pending(
    store: ApprovalStore,
    *,
    tool: str,
    args: str,
    session_id: str = "s1",
    ttl_s: float = 60.0,
    args_hash: str | None = None,
) -> ApprovalRequest:
    now = time.time()
    import hashlib

    if args_hash is None:
        args_hash = hashlib.sha256(
            json.dumps({"tool": tool, "args": args}, sort_keys=True).encode("utf-8")
        ).hexdigest()
    req = ApprovalRequest(
        id=store._next_id(),
        session_id=session_id,
        turn_id=None,
        channel="http",
        channel_id=None,
        tool_name=tool,
        risk_tier="sensitive",
        arguments=args[:2000],
        arguments_summary=args[:1500],
        arguments_full=args,
        diff_preview=None,
        requester="agent",
        status=STATUS_PENDING,
        decision_reason=None,
        decided_by=None,
        needs_double_confirm=False,
        double_confirm_window_s=5.0,
        args_hash=args_hash,
        ttl_s=ttl_s,
        created_at=now,
        expires_at=now + ttl_s,
        decided_at=None,
        consumed=False,
    )
    store.create(req)
    return req


def test_approve_via_rest(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    req = _make_pending(
        store, tool="write_file", args=json.dumps({"path": "x", "content": "y"})
    )
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{req.id}/decide",
            json={"action": "approve", "reason": "ok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["decision_reason"] == "ok"


def test_deny_via_rest(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    req = _make_pending(
        store, tool="run_bash", args=json.dumps({"command": "rm -rf"})
    )
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{req.id}/decide",
            json={"action": "deny", "reason": "dangerous"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "denied"
        assert body["decision_reason"] == "dangerous"


def test_cancel_via_rest(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    req = _make_pending(
        store,
        tool="edit_file",
        args=json.dumps({"path": "x", "old_text": "a", "new_text": "b"}),
    )
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{req.id}/cancel", json={"reason": "chat cancel"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cancelled"


def test_decide_unknown_approval_returns_404(tmp_path: Path) -> None:
    app, _store, _session, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/approvals/nonexistent/decide",
            json={"action": "approve"},
        )
        assert resp.status_code == 404


def test_bad_action_returns_400(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    req = _make_pending(
        store, tool="write_file", args=json.dumps({"path": "x", "content": "y"})
    )
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{req.id}/decide", json={"action": "kinda_yes"}
        )
        assert resp.status_code == 400


def test_session_policies_patch_and_read(tmp_path: Path) -> None:
    app, _store, session, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        # Read defaults (empty).
        resp = client.get(f"/api/sessions/{session.id}/policies")
        assert resp.status_code == 200
        body = resp.json()
        assert body["always_allow"] == []
        assert body["denied_tools"] == []

        # Patch in preauthorisation.
        resp = client.patch(
            f"/api/sessions/{session.id}/policies",
            json={"always_allow": ["run_bash", "edit_file"], "denied_tools": []},
        )
        assert resp.status_code == 200
        patched = resp.json()
        assert sorted(patched["always_allow"]) == ["edit_file", "run_bash"]

        # Read back.
        resp = client.get(f"/api/sessions/{session.id}/policies")
        assert sorted(resp.json()["always_allow"]) == ["edit_file", "run_bash"]


def test_session_policy_unknown_session(tmp_path: Path) -> None:
    app, _store, _session, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.patch(
            "/api/sessions/no-such/policies",
            json={"always_allow": ["write_file"]},
        )
        assert resp.status_code == 404


def test_session_policies_validation(tmp_path: Path) -> None:
    app, _store, session, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.patch(
            f"/api/sessions/{session.id}/policies",
            json={"always_allow": "not-a-list"},
        )
        assert resp.status_code == 400


def test_decide_remember_always(tmp_path: Path) -> None:
    app, store, _session, sessions = _build_app(tmp_path)
    req = _make_pending(
        store,
        tool="write_file",
        args=json.dumps({"path": "a/b.py", "content": "z"}),
        session_id=(_session := sessions.create()).id,
    )
    with TestClient(app) as client:
        resp = client.post(
            f"/api/approvals/{req.id}/decide",
            json={"action": "approve", "remember": "always"},
        )
        assert resp.status_code == 200
    loaded = sessions.get(req.session_id)
    assert loaded is not None
    assert "write_file" in loaded.meta.get("approvals.always", "")


def test_capabilities_endpoint(tmp_path: Path) -> None:
    app, _store, _session, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/api/approvals/capabilities")
        assert resp.status_code == 200
        body = resp.json()
        assert "write_file" in body["tools"]
        assert body["tools"]["write_file"]["requires_approval"] is True


def test_list_approvals_with_filters(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    _make_pending(
        store, tool="write_file", args=json.dumps({"path": "x", "content": "y"})
    )
    _make_pending(
        store, tool="run_bash", args=json.dumps({"command": "ls"})
    )
    with TestClient(app) as client:
        resp = client.get("/api/approvals", params={"tool_name": "write_file"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items and items[0]["tool_name"] == "write_file"


def test_get_approval(tmp_path: Path) -> None:
    app, store, _session, _ = _build_app(tmp_path)
    req = _make_pending(
        store, tool="write_file", args=json.dumps({"path": "x", "content": "y"})
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/approvals/{req.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == req.id
