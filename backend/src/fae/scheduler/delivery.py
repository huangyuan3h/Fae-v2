"""Unified notification delivery across inbox / WS / push / desktop / Telegram."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fae.notifications.desktop import send_desktop_notification
from fae.notifications.webpush import send_web_push
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.store import InboxItem, ScheduleStore

logger = logging.getLogger("fae.scheduler.delivery")

DEFAULT_SESSION_ID = "default"

# Async sender: full notification text → success
TelegramSender = Callable[[str], Awaitable[bool]]


def in_quiet_hours(
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


# Back-compat alias used by older tests / imports.
_in_quiet_hours = in_quiet_hours


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
        telegram_sender: TelegramSender | None = None,
    ) -> None:
        self.store = store
        self.hub = hub
        self.vapid_public_key = vapid_public_key
        self.vapid_private_key = vapid_private_key
        self.vapid_subject = vapid_subject
        self.notifications_enabled = notifications_enabled
        self._telegram_sender = telegram_sender

    def set_telegram_sender(self, sender: TelegramSender | None) -> None:
        self._telegram_sender = sender

    async def notify(
        self,
        title: str,
        body: str,
        *,
        session_id: str = DEFAULT_SESSION_ID,
        source: str = "system",
        skip_desktop: bool = False,
        skip_push: bool = False,
        skip_telegram: bool = False,
        speak: bool = True,
    ) -> InboxItem:
        sid = (session_id or "").strip() or DEFAULT_SESSION_ID
        item = self.store.add_inbox(
            title, body, session_id=sid, source=source
        )
        prefs = self.store.get_prefs()
        if not self.notifications_enabled or not prefs.enabled:
            return item

        quiet = in_quiet_hours(prefs.quiet_start_hour, prefs.quiet_end_hour)
        payload: dict[str, Any] = {
            "type": "notification",
            "id": item.id,
            "title": title,
            "body": body,
            "session_id": sid,
            "source": source,
            "created_at": item.created_at,
            "quiet": quiet,
            "speak": bool(speak) and not quiet,
        }

        # Always try WS so the open UI can show in-app toast / Notification API.
        try:
            await self.hub.broadcast(payload, session_id=sid)
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

        if self._telegram_sender is not None and not skip_telegram:
            text = f"{title}\n{body}".strip()
            try:
                await self._telegram_sender(text)
            except Exception:  # noqa: BLE001
                logger.debug("telegram notify failed", exc_info=True)

        return item
