"""HTTP surface for the sensitive-op approval flow.

Routes (all under ``/api/approvals``):

    GET    /api/approvals                  — list (filter by session_id, status, tool_name)
    GET    /api/approvals/{approval_id}    — detail
    POST   /api/approvals/{approval_id}/decide
                                          — body ``{"action", "reason?", "confirm"?, "remember"?}``
    POST   /api/approvals/{approval_id}/cancel
    PATCH  /api/sessions/{id}/policies     — session preauthorization
    GET    /api/sessions/{id}/policies    — read effective policy + raw meta keys

All clients (UI, CLI, Telegram, Scheduled jobs) talk to the same routes
regardless of transport.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from fae.approvals import (
    STATUS_APPROVED,
    VALID_ACTIONS,
    ApprovalStore,
)
from fae.sessions import Session
from fae.tool_registry import (
    EffectivePolicy,
    PolicyDecision,
    specs_for_capabilities,
)

logger = logging.getLogger("fae.api.approvals")

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_ALWAYS_KEY = "approvals.always"
_DENIED_KEY = "approvals.denied"


# ── Helpers ────────────────────────────────────────────────────────────
def _store(request: Request) -> ApprovalStore:
    store = getattr(request.app.state, "approvals", None)
    if not isinstance(store, ApprovalStore):
        raise HTTPException(status_code=503, detail="approvals store unavailable")
    return store


def _approval_dict(req: Any) -> dict[str, Any]:
    if hasattr(req, "to_dict"):
        return req.to_dict()
    return dict(req)


def _policy_from_session(session: Session) -> EffectivePolicy:
    raw_always = session.meta.get(_ALWAYS_KEY, "")
    raw_denied = session.meta.get(_DENIED_KEY, "")
    always = set()
    denied = set()
    if raw_always:
        for piece in raw_always.split(","):
            piece = piece.strip()
            if piece:
                always.add(piece)
    if raw_denied:
        for piece in raw_denied.split(","):
            piece = piece.strip()
            if piece:
                denied.add(piece)
    return EffectivePolicy(
        session_id=session.id,
        always_allow=frozenset(always),
        denied_tools=frozenset(denied),
    )


def _record_session_policy(session: Session, *, always_allow: list[str] | None, denied_tools: list[str] | None) -> EffectivePolicy:
    # mutate in place; ``Session.meta`` is the open dict we adopted for these keys.
    if always_allow is not None:
        session.meta[_ALWAYS_KEY] = ",".join(sorted({str(x).strip() for x in always_allow if str(x).strip()}))
        if not session.meta[_ALWAYS_KEY]:
            session.meta.pop(_ALWAYS_KEY, None)
    if denied_tools is not None:
        session.meta[_DENIED_KEY] = ",".join(sorted({str(x).strip() for x in denied_tools if str(x).strip()}))
        if not session.meta[_DENIED_KEY]:
            session.meta.pop(_DENIED_KEY, None)
    return _policy_from_session(session)


# ── Routes ─────────────────────────────────────────────────────────────
@router.get("/capabilities")
async def get_capabilities() -> dict[str, Any]:
    """Public catalog of tool specs (risk tier + needs approval)."""
    return {"tools": specs_for_capabilities()}


@router.get("")
async def list_approvals(
    request: Request,
    session_id: str | None = None,
    tool_name: str | None = None,
    status: str | None = None,
    before: float | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    store = _store(request)
    rows = await _run(
        store.list_requests,
        session_id=session_id,
        tool_name=tool_name,
        status=status,
        before=before,
        limit=limit,
    )
    return {
        "items": [_approval_dict(r) for r in rows],
        "count": len(rows),
    }


@router.get("/{approval_id}")
async def get_approval(request: Request, approval_id: str) -> dict[str, Any]:
    store = _store(request)
    req = await _run(store.get, approval_id)
    if req is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "approval_id": approval_id})
    return _approval_dict(req)


@router.post("/{approval_id}/decide")
async def decide_approval(
    request: Request,
    approval_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    store = _store(request)
    action = str(body.get("action") or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_action",
                "expected": sorted(VALID_ACTIONS),
            },
        )
    reason = body.get("reason")
    confirm = bool(body.get("confirm", False))
    decided_by = str(body.get("decided_by") or "user")
    remember = body.get("remember")
    sessions = getattr(request.app.state, "sessions", None)

    existing = await _run(store.get, approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "approval_id": approval_id})

    try:
        updated = await _run(
            store.resolve,
            approval_id,
            action=action,
            reason=reason,
            decided_by=decided_by,
            confirm=confirm,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "not_found", "approval_id": approval_id})

    # If the approval is approved AND caller asked to remember, write back the policy.
    if action == "approve" and remember and isinstance(sessions, object):
        from fae.sessions import SessionStore

        if isinstance(sessions, SessionStore):
            session = sessions.get(existing.session_id)
            if session is not None:
                if remember == "always":
                    current = session.meta.get(_ALWAYS_KEY, "")
                    pieces = {p.strip() for p in current.split(",") if p.strip()}
                    pieces.add(existing.tool_name)
                    session.meta[_ALWAYS_KEY] = ",".join(sorted(pieces))
                elif remember == "session":
                    # Session-scoped by-policy: cache ``consumed=1`` row.
                    store.mark_consumed(existing.id)

    return _approval_dict(updated)


@router.post("/{approval_id}/cancel")
async def cancel_approval(
    request: Request,
    approval_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = _store(request)
    reason = (body or {}).get("reason")
    updated = await _run(
        store.resolve,
        approval_id,
        action="cancel",
        reason=reason,
        decided_by=(body or {}).get("decided_by") or "user",
        confirm=False,
    )
    return _approval_dict(updated)


# ── Session preauthorization ───────────────────────────────────────────
from fastapi import APIRouter as _Router  # noqa: E402  (alias keeps diff focused)

session_policies_router = _Router(prefix="/api/sessions", tags=["approvals"])


@session_policies_router.get("/{session_id}/policies")
async def get_session_policies(request: Request, session_id: str) -> dict[str, Any]:
    from fae.sessions import SessionStore

    sessions = getattr(request.app.state, "sessions", None)
    if not isinstance(sessions, SessionStore):
        raise HTTPException(status_code=503, detail="session store unavailable")
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    policy = _policy_from_session(session)
    return {
        "session_id": session.id,
        "always_allow": sorted(policy.always_allow),
        "denied_tools": sorted(policy.denied_tools),
        "raw_meta": {k: v for k, v in session.meta.items() if k.startswith("approvals.")},
    }


@session_policies_router.patch("/{session_id}/policies")
async def patch_session_policies(
    request: Request,
    session_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    from fae.sessions import SessionStore

    sessions = getattr(request.app.state, "sessions", None)
    if not isinstance(sessions, SessionStore):
        raise HTTPException(status_code=503, detail="session store unavailable")
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    always_allow = body.get("always_allow")
    denied_tools = body.get("denied_tools")
    if always_allow is not None and not isinstance(always_allow, list):
        raise HTTPException(status_code=400, detail="always_allow must be a list")
    if denied_tools is not None and not isinstance(denied_tools, list):
        raise HTTPException(status_code=400, detail="denied_tools must be a list")
    policy = _record_session_policy(
        session,
        always_allow=always_allow,
        denied_tools=denied_tools,
    )
    return {
        "session_id": session.id,
        "always_allow": sorted(policy.always_allow),
        "denied_tools": sorted(policy.denied_tools),
    }


# ── Async helper ──────────────────────────────────────────────────────
async def _run(func: Any, *args: Any, **kwargs: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)
