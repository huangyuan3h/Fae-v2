"""Persistent task state machine — REST surface.

The agent commits to long-lived units of work (research the user asked
about, follow-up after a tool failure, run a job across multiple
channels). Each unit is a ``Task`` row in ``fae.scheduler.tasks`` with a
documented status graph:

    queued → running → done | failed
                  ↘ needs_input ↗
                  ↘ cancelled
    failed | cancelled → queued    (operator retry, attempts += 1)

Endpoints
  POST   /api/tasks                       create (supports Idempotency-Key)
  GET    /api/tasks                       list (filters + cursor)
  GET    /api/tasks/summary               status counts
  GET    /api/tasks/{task_id}             fetch (incl. progress + error_history)
  POST   /api/tasks/{task_id}/claim       queued | needs_input → running
  POST   /api/tasks/{task_id}/needs-input running → needs_input
  POST   /api/tasks/{task_id}/provide-input
                                          needs_input → running
  POST   /api/tasks/{task_id}/complete    running → done
  POST   /api/tasks/{task_id}/fail        running | needs_input → failed
  POST   /api/tasks/{task_id}/cancel      any non-terminal → cancelled
  POST   /api/tasks/{task_id}/retry       failed | cancelled → queued
  PATCH  /api/tasks/{task_id}/progress    merge progress dict (non-terminal)

Idempotency:
  ``POST /api/tasks`` honours the ``Idempotency-Key`` header. Repeats
  with the same key + matching fingerprint replay the original task
  (HTTP 201 with the same id); mismatched fingerprints return 409
  ``idempotency_conflict`` so the caller can detect divergent retries.

Invalid transitions / exhausted attempts / duplicate terminal actions
return HTTP 409 (Conflict).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from fae.scheduler.tasks import (
    AttemptsExhausted,
    IdempotencyConflict,
    InvalidTaskTransition,
    Task,
    TaskNotFound,
    TaskStatus,
    TaskStore,
    is_parked,
    is_terminal,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ── Schemas ──────────────────────────────────────────────────────────


class TaskCreateBody(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    channel: str | None = None
    parent_id: str | None = None
    max_attempts: int = Field(default=1, ge=1, le=20)


class TaskNeedsInputBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] | None = None
    note: str | None = None


class TaskProvideInputBody(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class TaskCompleteBody(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class TaskFailBody(BaseModel):
    error_code: str = Field(min_length=1, max_length=64)
    error_message: str | None = None
    note: str | None = None


class TaskNoteBody(BaseModel):
    note: str | None = None


class TaskProgressBody(BaseModel):
    progress: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class TaskOut(BaseModel):
    id: str
    kind: str
    title: str
    status: str
    parent_id: str | None
    session_id: str
    channel: str
    attempts: int
    max_attempts: int
    payload: dict[str, Any]
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    resume_token: dict[str, Any]
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None
    is_terminal: bool
    is_parked: bool
    extra: dict[str, Any]
    notes: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str | None = None
    fingerprint: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    error_history: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_task(
        cls,
        task: Task,
        *,
        error_history: list[dict[str, Any]] | None = None,
    ) -> "TaskOut":
        return cls(
            id=task.id,
            kind=task.kind,
            title=task.title,
            status=task.status,
            parent_id=task.parent_id,
            session_id=task.session_id,
            channel=task.channel,
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            payload=task.payload,
            result=task.result_summary,
            error_code=task.error_code,
            error_message=task.error_message,
            resume_token=task.resume_token,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            is_terminal=is_terminal(task.status),
            is_parked=is_parked(task.status),
            extra=task.extra,
            notes=task.notes,
            idempotency_key=task.idempotency_key,
            fingerprint=task.fingerprint,
            progress=task.progress,
            error_history=error_history if error_history is not None else [],
        )


# ── Helpers ──────────────────────────────────────────────────────────


def _store(request: Request) -> TaskStore:
    store = getattr(request.app.state, "task_store", None)
    if not isinstance(store, TaskStore) or store.closed:
        raise HTTPException(status_code=503, detail="task store not ready")
    return store


def _conflict(exc: InvalidTaskTransition) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "invalid_transition",
            "from": exc.from_status,
            "to": exc.to_status,
        },
    )


def _conflict_message(message: str) -> HTTPException:
    return HTTPException(
        status_code=409, detail={"code": "invalid_state", "message": message}
    )


def _attempts_exhausted(exc: AttemptsExhausted) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "attempts_exhausted",
            "attempts": exc.attempts,
            "max_attempts": exc.max_attempts,
        },
    )


def _idempotency_conflict(exc: IdempotencyConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "idempotency_conflict",
            "task_id": exc.task_id,
            "idempotency_key": exc.key,
            "message": "Idempotency-Key already bound to a different payload.",
        },
    )


def _fingerprint(
    *, kind: str, title: str, payload: dict[str, Any], session_id: str | None
) -> str:
    """Stable fingerprint over the request fields that distinguish
    idempotent calls. Excludes transient fields (created_at / channel)."""
    canonical = json.dumps(
        {
            "kind": kind,
            "title": title,
            "payload": dict(payload),
            "session_id": session_id or "default",
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:32]


# ── Routes ───────────────────────────────────────────────────────────


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreateBody,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskOut:
    store = _store(request)
    safe_key = (idempotency_key or "").strip() or None
    session_id = body.session_id or "default"
    fingerprint = _fingerprint(
        kind=body.kind,
        title=body.title,
        payload=body.payload,
        session_id=session_id,
    )
    try:
        task = await asyncio.to_thread(
            store.create_task,
            kind=body.kind,
            title=body.title,
            payload=body.payload,
            session_id=session_id,
            channel=body.channel or "http",
            parent_id=body.parent_id,
            max_attempts=body.max_attempts,
            idempotency_key=safe_key,
            fingerprint=fingerprint if safe_key else None,
        )
    except IdempotencyConflict as exc:
        raise _idempotency_conflict(exc) from exc
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    error_history = await asyncio.to_thread(store.error_history, task.id)
    return TaskOut.from_task(task, error_history=error_history)


@router.get("/summary", response_model=dict[str, int])
async def task_summary(
    request: Request,
    session_id: Annotated[str | None, Query()] = None,
) -> dict[str, int]:
    store = _store(request)
    counts = await asyncio.to_thread(store.status_counts, session_id=session_id)
    return counts


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    request: Request,
    status: Annotated[str | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    session_id: Annotated[str | None, Query()] = None,
    before: Annotated[float | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TaskOut]:
    store = _store(request)
    if status is not None and status not in {s.value for s in TaskStatus}:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_status", "status": status},
        )
    tasks = await asyncio.to_thread(
        store.list_tasks,
        status=status,
        kind=kind,
        session_id=session_id,
        before=before,
        limit=limit,
    )
    return [TaskOut.from_task(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, request: Request) -> TaskOut:
    store = _store(request)
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    error_history = await asyncio.to_thread(store.error_history, task.id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/claim", response_model=TaskOut)
async def claim_task(
    task_id: str, body: TaskNoteBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(store.claim, task_id, note=body.note)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except AttemptsExhausted as exc:
        raise _attempts_exhausted(exc) from exc
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/needs-input", response_model=TaskOut)
async def task_needs_input(
    task_id: str, body: TaskNeedsInputBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(
            store.request_input,
            task_id,
            prompt=body.prompt,
            resume_token=body.context,
            note=body.note,
        )
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/provide-input", response_model=TaskOut)
async def task_provide_input(
    task_id: str, body: TaskProvideInputBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(
            store.provide_input,
            task_id,
            input_payload=body.input,
            note=body.note,
        )
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/complete", response_model=TaskOut)
async def task_complete(
    task_id: str, body: TaskCompleteBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(
            store.complete,
            task_id,
            result=body.result,
            note=body.note,
        )
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/fail", response_model=TaskOut)
async def task_fail(
    task_id: str, body: TaskFailBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(
            store.fail,
            task_id,
            error_code=body.error_code,
            error_message=body.error_message,
            note=body.note,
        )
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.patch("/{task_id}/progress", response_model=TaskOut)
async def task_progress(
    task_id: str, body: TaskProgressBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(
            store.update_progress,
            task_id,
            progress=body.progress,
            note=body.note,
        )
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def task_cancel(
    task_id: str, body: TaskNoteBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(store.cancel, task_id, note=body.note)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    if task.status == TaskStatus.CANCELLED.value:
        return TaskOut.from_task(task)
    if task.status in {
        TaskStatus.DONE.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }:
        raise _conflict_message("task already in a terminal state")
    return TaskOut.from_task(task)


@router.post("/{task_id}/retry", response_model=TaskOut)
async def task_retry(
    task_id: str, body: TaskNoteBody, request: Request
) -> TaskOut:
    store = _store(request)
    try:
        task = await asyncio.to_thread(store.retry, task_id, note=body.note)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    except InvalidTaskTransition as exc:
        raise _conflict(exc) from exc
    error_history = await asyncio.to_thread(store.error_history, task_id)
    return TaskOut.from_task(task, error_history=error_history)


__all__ = ["router"]
