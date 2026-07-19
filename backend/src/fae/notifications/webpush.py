"""Web Push via pywebpush (optional when VAPID keys are configured)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("fae.notifications.webpush")


def send_web_push(
    *,
    subscription: dict[str, Any],
    payload: dict[str, Any],
    vapid_private_key: str,
    vapid_claims: dict[str, str],
) -> bool:
    """Send one Web Push message. Returns False if skipped or failed."""
    if not vapid_private_key:
        return False
    try:
        from pywebpush import webpush
    except ImportError:
        logger.warning("pywebpush not installed; skipping web push")
        return False
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.debug("web push failed", exc_info=True)
        return False
