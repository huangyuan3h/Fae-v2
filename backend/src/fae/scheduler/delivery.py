"""Unified notification delivery across inbox / WS / push / desktop."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fae.notifications.desktop import send_desktop_notification
from fae.notifications.webpush import send_web_push
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.store import InboxItem, ScheduleStore

logger = logging.getLogger("fae.scheduler.delivery")


def _in_quiet_hours(
    quiet_start: int | None,
    quiet_end: int | None,
    *,
    now_hour: int | None = None,
) -> bool:
    if quiet_start is None or quiet_end is None:
        return False
    hour = now_hour if now_hour is not None else datetime.now().hour
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= hour < quiet_end
    # wraps midnight
    return hour >= quiet_start or hour < quiet_end


class NotificationDelivery:
    def __init__(
        self,
        store: ScheduleStore,
        hub: ConnectionHub,
        *,
        vapid_public_key: str = "",
        vapid_private_key: str = "",
        vapid_subject: str = "mailto:fae@localhost",
        notifications_enabled: bool = True,
    ) -> None:
        self.store = store
        self.hub = hub
        self.vapid_public_key = vapid_public_key
        self.vapid_private_key = vapid_private_key
        self.vapid_subject = vapid_subject
        self.notifications_enabled = notifications_enabled

    async def notify(
        self,
        title: str,
        body: str,
        *,
        session_id: str = "",
        source: str = "system",
        skip_desktop: bool = False,
        skip_push: bool = False,
    ) -> InboxItem:
        item = self.store.add_inbox(
            title, body, session_id=session_id, source=source
        )
        prefs = self.store.get_prefs()
        if not self.notifications_enabled or not prefs.enabled:
            return item

        quiet = _in_quiet_hours(prefs.quiet_start_hour, prefs.quiet_end_hour)
        payload: dict[str, Any] = {
            "type": "notification",
            "id": item.id,
            "title": title,
            "body": body,
            "session_id": session_id,
            "source": source,
            "created_at": item.created_at,
            "quiet": quiet,
        }

        # Always try WS so the open UI can show in-app toast / Notification API.
        try:
            await self.hub.broadcast(payload, session_id=session_id or None)
        except Exception:  # noqa: BLE001
            logger.debug("ws broadcast failed", exc_info=True)

        if quiet:
            return item

        if prefs.desktop_enabled and not skip_desktop:
            send_desktop_notification(title, body)

        if (
            prefs.web_push_enabled
            and not skip_push
            and self.vapid_private_key
        ):
            claims = {"sub": self.vapid_subject}
            for sub in self.store.list_push_subscriptions():
                send_web_push(
                    subscription={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    payload={
                        "title": title,
                        "body": body,
                        "id": item.id,
                    },
                    vapid_private_key=self.vapid_private_key,
                    vapid_claims=claims,
                )
        return item
