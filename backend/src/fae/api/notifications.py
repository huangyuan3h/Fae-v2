"""Notification inbox, prefs, and Web Push subscription API (Phase 4.4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fae.scheduler.store import NotificationPrefs, ScheduleStore

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _store(request: Request) -> ScheduleStore:
    store = getattr(request.app.state, "schedule_store", None)
    if not isinstance(store, ScheduleStore):
        raise HTTPException(status_code=503, detail="scheduler store not ready")
    return store


class PrefsBody(BaseModel):
    enabled: bool | None = None
    quiet_start_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_end_hour: int | None = Field(default=None, ge=0, le=23)
    desktop_enabled: bool | None = None
    web_push_enabled: bool | None = None
    clear_quiet: bool = False


class SubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1)
    keys: dict[str, str]


class ReadBody(BaseModel):
    ids: list[str] | None = None


@router.get("")
async def list_notifications(
    request: Request,
    limit: int = 50,
    unread_only: bool = False,
) -> dict[str, Any]:
    store = _store(request)
    items = store.list_inbox(limit=limit, unread_only=unread_only)
    return {
        "items": [
            {
                "id": i.id,
                "title": i.title,
                "body": i.body,
                "session_id": i.session_id,
                "created_at": i.created_at,
                "read": i.read,
                "source": i.source,
            }
            for i in items
        ]
    }


@router.post("/read")
async def mark_read(body: ReadBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    n = store.mark_read(body.ids)
    return {"ok": True, "updated": n}


@router.get("/prefs")
async def get_prefs(request: Request) -> dict[str, Any]:
    prefs = _store(request).get_prefs()
    settings = request.app.state.settings
    return {
        "enabled": prefs.enabled,
        "quiet_start_hour": prefs.quiet_start_hour,
        "quiet_end_hour": prefs.quiet_end_hour,
        "desktop_enabled": prefs.desktop_enabled,
        "web_push_enabled": prefs.web_push_enabled,
        "vapid_configured": bool(getattr(settings, "vapid_public_key", "")),
    }


@router.put("/prefs")
async def put_prefs(body: PrefsBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    current = store.get_prefs()
    prefs = NotificationPrefs(
        enabled=current.enabled if body.enabled is None else body.enabled,
        quiet_start_hour=(
            None
            if body.clear_quiet
            else (
                current.quiet_start_hour
                if body.quiet_start_hour is None
                else body.quiet_start_hour
            )
        ),
        quiet_end_hour=(
            None
            if body.clear_quiet
            else (
                current.quiet_end_hour
                if body.quiet_end_hour is None
                else body.quiet_end_hour
            )
        ),
        desktop_enabled=(
            current.desktop_enabled
            if body.desktop_enabled is None
            else body.desktop_enabled
        ),
        web_push_enabled=(
            current.web_push_enabled
            if body.web_push_enabled is None
            else body.web_push_enabled
        ),
    )
    store.set_prefs(prefs)
    return {
        "enabled": prefs.enabled,
        "quiet_start_hour": prefs.quiet_start_hour,
        "quiet_end_hour": prefs.quiet_end_hour,
        "desktop_enabled": prefs.desktop_enabled,
        "web_push_enabled": prefs.web_push_enabled,
    }


@router.get("/vapid-public-key")
async def vapid_public_key(request: Request) -> dict[str, str]:
    key = getattr(request.app.state.settings, "vapid_public_key", "") or ""
    if not key:
        raise HTTPException(status_code=404, detail="VAPID not configured")
    return {"publicKey": key}


@router.post("/subscribe")
async def subscribe(body: SubscribeBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    p256dh = body.keys.get("p256dh") or body.keys.get("p256DH") or ""
    auth = body.keys.get("auth") or ""
    if not p256dh or not auth:
        raise HTTPException(status_code=400, detail="keys.p256dh and keys.auth required")
    store.add_push_subscription(body.endpoint, p256dh, auth)
    return {"ok": True}


@router.delete("/subscribe")
async def unsubscribe(body: SubscribeBody, request: Request) -> dict[str, Any]:
    store = _store(request)
    ok = store.remove_push_subscription(body.endpoint)
    return {"ok": ok}
