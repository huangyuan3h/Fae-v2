"""LLM-callable schedule tools (shared with REST)."""

from __future__ import annotations

import json
from typing import Any

from fae.scheduler.parse_nl import parse_schedule_text
from fae.scheduler.store import ScheduleStore, StoredJob

SCHEDULE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "schedule_create_job",
            "description": (
                "Create a reminder or cron job from natural language "
                "(e.g. '明天8点提醒吃维生素' or '每天9点喝水')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Natural language schedule request",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jobs",
            "description": "List scheduled jobs (builtin and custom).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_job",
            "description": "Cancel/delete a custom job by id (builtin jobs are disabled).",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
            },
        },
    },
]


def create_job_from_text(store: ScheduleStore, text: str) -> StoredJob:
    parsed = parse_schedule_text(text)
    return store.create_custom_job(
        kind=parsed.kind,
        title=parsed.title,
        body=parsed.body or text,
        cron=parsed.cron,
        run_at=parsed.run_at,
        meta={"raw_text": parsed.raw_text},
    )


def tool_list_jobs(store: ScheduleStore) -> list[dict[str, Any]]:
    return [
        {
            "id": j.id,
            "kind": j.kind,
            "title": j.title,
            "cron": j.cron,
            "run_at": j.run_at,
            "enabled": j.enabled,
            "builtin": j.builtin,
        }
        for j in store.list_jobs()
    ]


def tool_cancel_job(store: ScheduleStore, job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        return {"ok": False, "error": "not_found"}
    if job.builtin:
        store.patch_job(job_id, enabled=False)
        return {"ok": True, "disabled": True, "id": job_id}
    store.delete_job(job_id)
    return {"ok": True, "deleted": True, "id": job_id}


def dispatch_schedule_tool(
    store: ScheduleStore,
    name: str,
    arguments: str | dict[str, Any],
) -> str:
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}
    if name == "schedule_create_job":
        job = create_job_from_text(store, str(args.get("text") or ""))
        return json.dumps(
            {
                "ok": True,
                "id": job.id,
                "kind": job.kind,
                "title": job.title,
                "cron": job.cron,
                "run_at": job.run_at,
            }
        )
    if name == "list_jobs":
        return json.dumps({"jobs": tool_list_jobs(store)})
    if name == "cancel_job":
        return json.dumps(tool_cancel_job(store, str(args.get("job_id") or "")))
    return json.dumps({"ok": False, "error": f"unknown tool {name}"})
