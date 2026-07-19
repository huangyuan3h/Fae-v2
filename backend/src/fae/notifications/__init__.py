"""Notification channels (Phase 4.4)."""

from __future__ import annotations

from fae.notifications.desktop import send_desktop_notification
from fae.notifications.webpush import send_web_push

__all__ = ["send_desktop_notification", "send_web_push"]
