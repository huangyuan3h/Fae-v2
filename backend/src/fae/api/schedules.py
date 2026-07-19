"""HTTP API for scheduled jobs (Phase 4) + scheduler status (Q.2)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fae.scheduler.activity import ActivityTracker
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.parse_nl import parse_schedule_text
from fae.scheduler.store import ScheduleStore
from fae.scheduler.tools import create_job_from_text

router = APIRouter(prefix="/api/schedules", tags=["schedules"])
status_router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


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
            if job.kind == "date":
                store.patch_job(job_id, enabled=False)
            await delivery.notify(
                job.title or "提醒",
                job.body or job.title,
                source=f"job:{job_id}",
            )
            return {"ok": True, "id": job_id, "via": "delivery"}
        raise HTTPException(status_code=503, detail="proactive loop not running")
    return await loop.run_job(job_id)


@status_router.get("/status")
async def scheduler_status(request: Request) -> dict[str, Any]:
    """Idle / outreach / proactive LLM readiness for Settings verification UX."""
    settings = request.app.state.settings
    store = getattr(request.app.state, "schedule_store", None)
    activity = getattr(request.app.state, "activity", None)
    loop = _loop(request)
    prefs = store.get_prefs() if isinstance(store, ScheduleStore) else None

    key = (
        (getattr(settings, "proactive_llm_api_key", "") or "").strip()
        or (getattr(settings, "dashscope_api_key", "") or "").strip()
    )
    llm_ready = bool(key) and key != "unused"

    sid = "default"
    last_activity: float | None = None
    idle_seconds: float | None = None
    if isinstance(activity, ActivityTracker):
        last_activity = activity.last_at(sid)
        idle_seconds = activity.idle_seconds(sid)

    last_outreach_at: float | None = None
    outreach_count_today = 0
    outreach_day: str | None = None
    if isinstance(store, ScheduleStore):
        day, count, last_at = store.get_outreach_state(sid)
        outreach_day, outreach_count_today, last_outreach_at = day, count, last_at
    if loop is not None:
        hb = loop.heartbeat
        last_outreach_at = hb._last_outreach_at.get(sid, last_outreach_at)
        outreach_count_today = hb._outreach_count.get(sid, outreach_count_today)
        outreach_day = hb._outreach_day.get(sid, outreach_day)

    idle_hours = float(getattr(settings, "outreach_idle_hours", 6.0))
    next_eligible_in: float | None = None
    if idle_seconds is not None:
        need = idle_hours * 3600
        if idle_seconds < need:
            next_eligible_in = need - idle_seconds

    return {
        "scheduler_enabled": bool(loop is not None and loop._started),
        "session_id": sid,
        "now": time.time(),
        "last_activity_at": last_activity,
        "idle_seconds": idle_seconds,
        "outreach_idle_hours": idle_hours,
        "next_eligible_in_seconds": next_eligible_in,
        "last_outreach_at": last_outreach_at,
        "outreach_count_today": outreach_count_today,
        "outreach_day": outreach_day,
        "proactive_enabled": prefs.proactive_enabled if prefs else True,
        "proactive_llm_ready": llm_ready,
        "unread_inbox": (
            len(store.list_inbox(limit=50, unread_only=True))
            if isinstance(store, ScheduleStore)
            else 0
        ),
    }
