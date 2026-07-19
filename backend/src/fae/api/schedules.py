"""HTTP API for scheduled jobs (Phase 4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.parse_nl import parse_schedule_text
from fae.scheduler.store import ScheduleStore
from fae.scheduler.tools import create_job_from_text

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _store(request: Request) -> ScheduleStore:
    store = getattr(request.app.state, "schedule_store", None)
    if not isinstance(store, ScheduleStore):
        raise HTTPException(status_code=503, detail="scheduler store not ready")
    return store


def _loop(request: Request) -> ProactiveLoop | None:
    loop = getattr(request.app.state, "proactive", None)
    return loop if isinstance(loop, ProactiveLoop) else None


class ScheduleCreate(BaseModel):
    text: str | None = None
    title: str | None = None
    body: str = ""
    cron: str | None = None
    run_at: float | None = None
    kind: str | None = None


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    title: str | None = None
    body: str | None = None
    cron: str | None = None


class ParseBody(BaseModel):
    text: str = Field(min_length=1)


def _job_out(job: Any, loop: ProactiveLoop | None) -> dict[str, Any]:
    next_run = None
    if loop is not None:
        next_run = loop.job_next_run(job.id)
    if next_run is None and job.run_at and job.enabled:
        next_run = job.run_at
    return {
        "id": job.id,
        "kind": job.kind,
        "title": job.title,
        "body": job.body,
        "cron": job.cron,
        "run_at": job.run_at,
        "enabled": job.enabled,
        "builtin": job.builtin,
        "meta": job.meta,
        "next_run": next_run,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("")
async def list_schedules(request: Request) -> dict[str, Any]:
    store = _store(request)
    loop = _loop(request)
    jobs = [_job_out(j, loop) for j in store.list_jobs()]
    return {
        "jobs": jobs,
        "scheduler_enabled": bool(loop is not None and loop._started),
    }


@router.post("/parse")
async def parse_schedule(body: ParseBody) -> dict[str, Any]:
    try:
        parsed = parse_schedule_text(body.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "kind": parsed.kind,
        "title": parsed.title,
        "body": parsed.body,
        "cron": parsed.cron,
        "run_at": parsed.run_at,
        "raw_text": parsed.raw_text,
    }


@router.post("")
async def create_schedule(body: ScheduleCreate, request: Request) -> dict[str, Any]:
    store = _store(request)
    loop = _loop(request)
    try:
        if body.text and body.text.strip():
            job = create_job_from_text(store, body.text.strip())
        elif body.cron:
            job = store.create_custom_job(
                kind="cron",
                title=body.title or "cron job",
                body=body.body,
                cron=body.cron,
            )
        elif body.run_at is not None:
            job = store.create_custom_job(
                kind="date",
                title=body.title or "reminder",
                body=body.body,
                run_at=body.run_at,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide text, cron, or run_at",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if loop is not None:
        loop.resync()
    return _job_out(job, loop)


@router.patch("/{job_id}")
async def patch_schedule(
    job_id: str, body: SchedulePatch, request: Request
) -> dict[str, Any]:
    store = _store(request)
    loop = _loop(request)
    job = store.patch_job(
        job_id,
        enabled=body.enabled,
        title=body.title,
        body=body.body,
        cron=body.cron,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if loop is not None:
        loop.resync()
    return _job_out(job, loop)


@router.delete("/{job_id}")
async def delete_schedule(job_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    loop = _loop(request)
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.builtin:
        store.patch_job(job_id, enabled=False)
        if loop is not None:
            loop.resync()
        return {"ok": True, "disabled": True, "id": job_id}
    store.delete_job(job_id)
    if loop is not None:
        loop.resync()
    return {"ok": True, "deleted": True, "id": job_id}


@router.post("/{job_id}/trigger")
async def trigger_schedule(job_id: str, request: Request) -> dict[str, Any]:
    loop = _loop(request)
    store = _store(request)
    if store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if loop is None:
        # Still deliver via store if delivery available
        delivery = getattr(request.app.state, "delivery", None)
        job = store.get_job(job_id)
        assert job is not None
        if delivery is not None:
            await delivery.notify(
                job.title or "提醒",
                job.body or job.title,
                source=f"job:{job_id}",
            )
            return {"ok": True, "id": job_id, "via": "delivery"}
        raise HTTPException(status_code=503, detail="proactive loop not running")
    return await loop.run_job(job_id)
