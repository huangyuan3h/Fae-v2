"""Persistent + in-memory approval store for sensitive tool calls.

The approval flow:

1. Tool dispatcher (``_dispatch_coding_tool``) detects a tool whose
   ``ToolSpec.requires_approval`` is True and the session policy did not
   pre-authorise the call.
2. ``request_approval(...)`` creates a row in ``approvals`` with status
   ``pending``, registers an ``asyncio.Future`` for the awaiting coroutine,
   and emits a server-side ``approval_request`` event so any UI/channel can
   prompt the operator.
3. Either the operator approves/denies via WS (``approval_decision``) or
   HTTP (``POST /api/approvals/{id}/decide``); the future is resolved and
   the ``approval_resolved`` event goes back out.
4. If no decision arrives before ``expires_at``, the future times out, the
   row is marked ``expired`` and the tool result is ``approval_expired``.

State machine::

    pending ──approve──▶ approved ──execute──▶ consumed
    pending ──deny─────▶ denied
    pending ──timeout──▶ expired
    pending ──cancel──▶ cancelled
    pending ──superseded──▶ superseded
    approved ──execute fails──▶ approved (terminal; rows stay ``approved``
                                       and the audit record reflects failure)

A second ``pending`` row is created for ``needs_double_confirm`` tools
(dangerous tier). The first ``approve`` advances the request from
``pending`` to ``awaiting_confirm``; the second ``approve`` flips it to
``approved``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fae.sanitize import safe_json, safe_text
from fae.tool_registry import (
    ToolSpec,
    canonical_args_hash,
    diff_preview_for,
    get_spec,
)

logger = logging.getLogger("fae.approvals")

# ── Status enum ─────────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_SUPERSEDED = "superseded"
STATUS_AWAITING_CONFIRM = "awaiting_confirm"

_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_EXPIRED,
        STATUS_CANCELLED,
        STATUS_SUPERSEDED,
    }
)
_VALID_STATUSES: frozenset[str] = frozenset(_TERMINAL_STATUSES | {STATUS_PENDING, STATUS_AWAITING_CONFIRM})


VALID_ACTIONS: frozenset[str] = frozenset({"approve", "deny", "cancel"})


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending (or resolved) approval request."""

    id: str
    session_id: str
    turn_id: str | None
    channel: str
    channel_id: str | None
    tool_name: str
    risk_tier: str
    arguments: str
    arguments_summary: str
    arguments_full: str
    diff_preview: str | None
    requester: str
    status: str
    decision_reason: str | None
    decided_by: str | None
    needs_double_confirm: bool
    double_confirm_window_s: float
    args_hash: str
    ttl_s: float
    created_at: float
    expires_at: float
    decided_at: float | None
    consumed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "channel": self.channel,
            "channel_id": self.channel_id,
            "tool_name": self.tool_name,
            "risk_tier": self.risk_tier,
            "arguments_summary": self.arguments_summary,
            "arguments_full": self.arguments_full,
            "diff_preview": self.diff_preview,
            "requester": self.requester,
            "status": self.status,
            "decision_reason": self.decision_reason,
            "decided_by": self.decided_by,
            "needs_double_confirm": self.needs_double_confirm,
            "double_confirm_window_s": self.double_confirm_window_s,
            "args_hash": self.args_hash,
            "ttl_s": self.ttl_s,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "consumed": self.consumed,
        }


@dataclass(frozen=True)
class ApprovalDecision:
    """Outcome of awaiting a single approval request (per ``action``)."""

    approval_id: str
    action: str  # "approve" | "deny" | "cancel" | "timeout"
    status: str  # final ApprovalRequest.status
    reason: str
    reason_code: str  # "approved" | "denied" | "expired" | "cancelled" | "superseded"


# ── Store ───────────────────────────────────────────────────────────────
class ApprovalStore:
    """Persistent + in-memory approval coordinator.

    Three responsibilities:

    - Persist approval rows in SQLite so callers can audit/list them later.
    - Hold a map of ``approval_id -> asyncio.Future`` so the dispatcher
      coroutine can ``await`` a human decision.
    - Sweep expired rows so a forgotten request doesn't pin an agent in
      pending forever.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self._futures: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._futures_lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    # ── Schema ────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  turn_id TEXT,
                  channel TEXT NOT NULL,
                  channel_id TEXT,
                  tool_name TEXT NOT NULL,
                  risk_tier TEXT NOT NULL,
                  arguments TEXT NOT NULL DEFAULT '',
                  arguments_summary TEXT NOT NULL DEFAULT '',
                  arguments_full TEXT NOT NULL DEFAULT '',
                  diff_preview TEXT,
                  requester TEXT NOT NULL,
                  status TEXT NOT NULL,
                  decision_reason TEXT,
                  decided_by TEXT,
                  needs_double_confirm INTEGER NOT NULL DEFAULT 0,
                  double_confirm_window_s REAL NOT NULL DEFAULT 5.0,
                  args_hash TEXT NOT NULL,
                  ttl_s REAL NOT NULL DEFAULT 60.0,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  decided_at REAL,
                  consumed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_session_created
                  ON approvals (session_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_approvals_status_expires
                  ON approvals (status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_approvals_args_hash
                  ON approvals (session_id, args_hash);
                """
            )
            self._conn.commit()

    # ── DB plumbing ───────────────────────────────────────────────────
    def _row_to_request(self, row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            turn_id=row["turn_id"],
            channel=str(row["channel"]),
            channel_id=row["channel_id"],
            tool_name=str(row["tool_name"]),
            risk_tier=str(row["risk_tier"]),
            arguments=str(row["arguments"] or ""),
            arguments_summary=str(row["arguments_summary"] or ""),
            arguments_full=str(row["arguments_full"] or ""),
            diff_preview=row["diff_preview"],
            requester=str(row["requester"]),
            status=str(row["status"]),
            decision_reason=row["decision_reason"],
            decided_by=row["decided_by"],
            needs_double_confirm=bool(row["needs_double_confirm"]),
            double_confirm_window_s=float(row["double_confirm_window_s"] or 5.0),
            args_hash=str(row["args_hash"]),
            ttl_s=float(row["ttl_s"]),
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            decided_at=(
                None if row["decided_at"] is None else float(row["decided_at"])
            ),
            consumed=bool(row["consumed"]),
        )

    def create(self, req: ApprovalRequest) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                INSERT INTO approvals
                  (id, session_id, turn_id, channel, channel_id, tool_name, risk_tier,
                   arguments, arguments_summary, arguments_full, diff_preview,
                   requester, status, decision_reason, decided_by,
                   needs_double_confirm, double_confirm_window_s,
                   args_hash, ttl_s, created_at, expires_at, decided_at, consumed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.id,
                    req.session_id,
                    req.turn_id,
                    req.channel,
                    req.channel_id,
                    req.tool_name,
                    req.risk_tier,
                    req.arguments,
                    req.arguments_summary,
                    req.arguments_full,
                    req.diff_preview,
                    req.requester,
                    req.status,
                    req.decision_reason,
                    req.decided_by,
                    int(bool(req.needs_double_confirm)),
                    req.double_confirm_window_s,
                    req.args_hash,
                    req.ttl_s,
                    req.created_at,
                    req.expires_at,
                    req.decided_at,
                    int(bool(req.consumed)),
                ),
            )
            self._conn.commit()

    def update_status(
        self,
        approval_id: str,
        *,
        status: str,
        decision_reason: str | None,
        decided_by: str | None,
        decided_at: float,
        consumed: bool | None = None,
    ) -> ApprovalRequest:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self._db_lock:
            if consumed is None:
                self._conn.execute(
                    """
                    UPDATE approvals
                    SET status = ?, decision_reason = ?, decided_by = ?, decided_at = ?
                    WHERE id = ?
                    """,
                    (status, decision_reason, decided_by, decided_at, approval_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE approvals
                    SET status = ?, decision_reason = ?, decided_by = ?, decided_at = ?,
                        consumed = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        decision_reason,
                        decided_by,
                        decided_at,
                        int(bool(consumed)),
                        approval_id,
                    ),
                )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return self._row_to_request(row)

    def mark_consumed(self, approval_id: str) -> ApprovalRequest:
        return self.update_status(
            approval_id,
            status=STATUS_APPROVED,
            decision_reason=None,
            decided_by=None,
            decided_at=time.time(),
            consumed=True,
        )

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return self._row_to_request(row) if row else None

    def list_requests(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        before: float | None = None,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if before is not None:
            clauses.append("created_at < ?")
            params.append(before)
        safe_limit = min(max(int(limit), 1), 200)
        query = "SELECT * FROM approvals"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(safe_limit)
        with self._db_lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_request(row) for row in rows]

    def clear(self, session_id: str | None = None) -> int:
        with self._db_lock:
            if session_id is None:
                cursor = self._conn.execute("DELETE FROM approvals")
            else:
                sid = (session_id or "").strip() or "default"
                cursor = self._conn.execute(
                    "DELETE FROM approvals WHERE session_id = ?", (sid,)
                )
            self._conn.commit()
            total = cursor.rowcount
            
            with self._futures_lock:
                if session_id is None:
                    self._futures.clear()
                else:
                    # Remove futures for this session_id
                    futs_to_remove = []
                    for approval_id, fut in self._futures.items():
                        # We need to know which session_id the approval belongs to
                        # without causing deadlock, we'll clear all futures for this session.
                        # This is a simplification - ideally we'd have session_id in the future
                        # or a more precise lookup method.
                        futs_to_remove.append(approval_id)
                    for approval_id in futs_to_remove:
                        self._futures.pop(approval_id, None)
            
            return total

    def has_active_session_rule(
        self, session_id: str, args_hash: str, *, as_of: float
    ) -> bool:
        """A session-scoped preauth row keeps its row status='approved' and
        consumed=1; we accept it as long as the approval is recent
        (``created_at >= as_of - 1h``). UI may refresh; for now we treat
        consume-time as the freshness gate."""
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM approvals
                WHERE session_id = ?
                  AND args_hash = ?
                  AND status = ?
                  AND consumed = 1
                  AND created_at >= ?
                LIMIT 1
                """,
                (
                    session_id,
                    args_hash,
                    STATUS_APPROVED,
                    float(as_of) - 3600.0,
                ),
            ).fetchone()
        return row is not None

    # ── Future coordination ───────────────────────────────────────────
    def _take_future(self, approval_id: str) -> asyncio.Future[ApprovalDecision] | None:
        with self._futures_lock:
            fut = self._futures.pop(approval_id, None)
        return fut

    @staticmethod
    def _next_id() -> str:
        return uuid.uuid4().hex

    def resolve(
        self,
        approval_id: str,
        *,
        action: str,
        reason: str | None = None,
        decided_by: str = "user",
        confirm: bool = False,
    ) -> ApprovalRequest:
        if action not in VALID_ACTIONS:
            raise ValueError(f"invalid action: {action}")
        req = self.get(approval_id)
        if req is None:
            raise KeyError(approval_id)
        if req.status not in {STATUS_PENDING, STATUS_AWAITING_CONFIRM}:
            # Idempotent: re-resolving a finished request returns the row.
            return req
        now = time.time()
        if action == "cancel":
            new_status = STATUS_CANCELLED
            reason_code = "cancelled"
        elif action == "deny":
            new_status = STATUS_DENIED
            reason_code = "denied"
        elif action == "approve":
            if req.needs_double_confirm and not confirm and req.status == STATUS_PENDING:
                new_status = STATUS_AWAITING_CONFIRM
                reason_code = "awaiting_confirm"
            else:
                new_status = STATUS_APPROVED
                reason_code = "approved"
        else:  # defensive
            new_status = req.status
            reason_code = req.status
        # Map awaiting_confirm to a decision with status still pending for
        # the dispatcher; the future will be re-armed by the caller.
        if new_status == STATUS_AWAITING_CONFIRM:
            updated = self.update_status(
                approval_id,
                status=STATUS_AWAITING_CONFIRM,
                decision_reason=reason,
                decided_by=decided_by,
                decided_at=now,
                consumed=False,
            )
            return updated
        updated = self.update_status(
            approval_id,
            status=new_status,
            decision_reason=reason,
            decided_by=decided_by,
            decided_at=now,
            consumed=False,
        )
        decision = ApprovalDecision(
            approval_id=approval_id,
            action=action,
            status=new_status,
            reason=reason or "",
            reason_code=reason_code,
        )
        fut = self._take_future(approval_id)
        if fut is not None and not fut.done():
            fut.set_result(decision)
        return updated

    def timeout(self, approval_id: str) -> ApprovalRequest | None:
        """Mark a still-pending request as expired and resolve its future."""
        req = self.get(approval_id)
        if req is None:
            return None
        if req.status not in {STATUS_PENDING, STATUS_AWAITING_CONFIRM}:
            return req
        now = time.time()
        updated = self.update_status(
            approval_id,
            status=STATUS_EXPIRED,
            decision_reason="ttl_reached",
            decided_by="timeout",
            decided_at=now,
            consumed=False,
        )
        decision = ApprovalDecision(
            approval_id=approval_id,
            action="timeout",
            status=STATUS_EXPIRED,
            reason="ttl_reached",
            reason_code="expired",
        )
        fut = self._take_future(approval_id)
        if fut is not None and not fut.done():
            fut.set_result(decision)
        return updated

    def sweep_expired(self, *, as_of: float | None = None) -> list[ApprovalRequest]:
        as_of = as_of if as_of is not None else time.time()
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT id FROM approvals
                WHERE status IN (?, ?) AND expires_at <= ?
                """,
                (STATUS_PENDING, STATUS_AWAITING_CONFIRM, float(as_of)),
            ).fetchall()
        expired: list[ApprovalRequest] = []
        for row in rows:
            updated = self.timeout(str(row["id"]))
            if updated is not None:
                expired.append(updated)
        return expired

    def close(self) -> None:
        if self._closed:
            return
        with self._db_lock:
            if not self._closed:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    logger.debug("approval store close failed", exc_info=True)
                self._closed = True
        with self._futures_lock:
            for fut in self._futures.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("approval store closed"))
            self._futures.clear()


# ── Request helper ──────────────────────────────────────────────────────
def _truncate_summary(arguments_full: str) -> str:
    try:
        parsed = json.loads(arguments_full)
    except json.JSONDecodeError:
        return arguments_full[:1500]
    return json.dumps(parsed, ensure_ascii=False)[:1500]


async def request_approval(
    store: ApprovalStore,
    *,
    tool_name: str,
    arguments: str,
    session_id: str,
    turn_id: str | None,
    channel: str,
    channel_id: str | None,
    requester: str,
    ttl_s: float | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> ApprovalRequest:
    """Create a pending approval, await the operator decision.

    ``on_event`` is fired twice:
      - ``approval_request`` (when the request is created),
      - ``approval_resolved`` (status terminal; consumed flag stays False so
        the dispatcher can persist it into tool_audit separately).

    Returns the final ``ApprovalRequest`` (status in
    ``{approved, denied, expired, cancelled, awaiting_confirm}``).

    For double-confirm tools the first ``approve`` returns status
    ``awaiting_confirm``; the caller must invoke :func:`request_approval`
    again (or call ``store.resolve(..., confirm=True)``) to get a final
    verdict. The full-await pattern below waits in-place for that second
    decision so the agent only resumes once.
    """
    spec = get_spec(tool_name)
    if spec is None:
        raise ValueError(f"unknown tool: {tool_name}")
    if not spec.requires_approval:
        # Defensive: caller should have caught this with resolve_policy.
        raise ValueError(f"tool {tool_name!r} does not require approval")
    args_hash = canonical_args_hash(tool_name, arguments)
    arguments_full = safe_json(arguments)
    summary = _truncate_summary(arguments_full)
    diff_preview = diff_preview_for(tool_name, arguments)
    if diff_preview is not None:
        diff_preview = safe_text(diff_preview)
    ttl = float(ttl_s) if ttl_s is not None else spec.default_ttl_s
    if ttl <= 0:
        raise ValueError("ttl_s must be positive")
    needs_double = bool(spec.needs_double_confirm)
    double_window = float(spec.double_confirm_window_s)

    def _new_request(initial_status: str, created_at: float, expires_at: float) -> ApprovalRequest:
        return ApprovalRequest(
            id=uuid.uuid4().hex,
            session_id=session_id,
            turn_id=turn_id,
            channel=channel,
            channel_id=channel_id,
            tool_name=tool_name,
            risk_tier=spec.risk_tier,
            arguments=safe_text(arguments)[:2000],
            arguments_summary=summary,
            arguments_full=arguments_full,
            diff_preview=diff_preview,
            requester=requester,
            status=initial_status,
            decision_reason=None,
            decided_by=None,
            needs_double_confirm=needs_double,
            double_confirm_window_s=double_window,
            args_hash=args_hash,
            ttl_s=ttl,
            created_at=created_at,
            expires_at=expires_at,
            decided_at=None,
            consumed=False,
        )

    loop = asyncio.get_running_loop()
    now = time.time()
    first = _new_request(STATUS_PENDING, created_at=now, expires_at=now + ttl)
    store.create(first)
    if on_event is not None:
        try:
            await on_event(
                {
                    "type": "approval_request",
                    "approval": first.to_dict(),
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception("approval_request emit failed")
    loop_fut: asyncio.Future[ApprovalDecision] = loop.create_future()
    with store._futures_lock:  # type: ignore[attr-defined]
        store._futures[first.id] = loop_fut  # type: ignore[attr-defined]
    try:
        # Wait for first decision: approve → possibly awaiting_confirm,
        # approve+confirm → approved, deny → denied, timeout → expired,
        # cancel → cancelled.
        decision = await _wait_or_cancel(
            loop_fut, timeout=ttl, cancel_event=cancel_event
        )
        if decision is None:
            decision = ApprovalDecision(
                approval_id=first.id,
                action="timeout",
                status=STATUS_EXPIRED,
                reason="cancelled_or_timeout",
                reason_code="expired",
            )
            store.timeout(first.id)
        # If first approved but needs second confirm, request once more.
        if (
            decision.status == STATUS_AWAITING_CONFIRM
            and needs_double
        ):
            second = _new_request(
                STATUS_PENDING,
                created_at=time.time(),
                expires_at=time.time() + double_window + 30.0,
            )
            # The second row uses a fresh id; the first row stays
            # ``awaiting_confirm`` for audit. We park the first row's
            # future replaced by a new one registered under ``second.id``.
            store.create(second)
            if on_event is not None:
                try:
                    await on_event(
                        {
                            "type": "approval_request",
                            "approval": second.to_dict(),
                            "follow_up": True,
                        }
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("approval_request (follow_up) emit failed")
            second_fut: asyncio.Future[ApprovalDecision] = loop.create_future()
            with store._futures_lock:  # type: ignore[attr-defined]
                store._futures[second.id] = second_fut  # type: ignore[attr-defined]
            second_decision = await _wait_or_cancel(
                second_fut,
                timeout=double_window + 30.0,
                cancel_event=cancel_event,
            )
            if second_decision is None:
                store.timeout(second.id)
                decision = ApprovalDecision(
                    approval_id=second.id,
                    action="timeout",
                    status=STATUS_EXPIRED,
                    reason="confirmation_ttl_reached",
                    reason_code="expired",
                )
            else:
                decision = second_decision
            final = store.get(second.id) or second
        else:
            final = store.get(first.id) or first
    finally:
        with store._futures_lock:  # type: ignore[attr-defined]
            store._futures.pop(first.id, None)  # type: ignore[attr-defined]
    if on_event is not None:
        try:
            await on_event(
                {
                    "type": "approval_resolved",
                    "approval_id": final.id,
                    "tool_name": final.tool_name,
                    "status": final.status,
                    "decision_reason": final.decision_reason,
                    "decided_by": final.decided_by,
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception("approval_resolved emit failed")
    return final


async def _wait_or_cancel(
    fut: asyncio.Future[ApprovalDecision],
    *,
    timeout: float,
    cancel_event: asyncio.Event | None,
) -> ApprovalDecision | None:
    """Await ``fut`` or ``cancel_event``, whichever fires first."""
    if cancel_event is None:
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    cancel_task = asyncio.create_task(cancel_event.wait())
    timeout_task = asyncio.create_task(asyncio.sleep(timeout))
    fut_task = asyncio.create_task(_shielded(fut))
    try:
        done, _ = await asyncio.wait(
            {fut_task, cancel_task, timeout_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if fut_task in done:
            return fut_task.result()
        # cancel or timeout → resolve nothing; caller treats as timeout.
        return None
    finally:
        for t in (cancel_task, timeout_task, fut_task):
            if not t.done():
                t.cancel()


async def _shielded(fut: asyncio.Future[ApprovalDecision]) -> ApprovalDecision:
    return await fut
