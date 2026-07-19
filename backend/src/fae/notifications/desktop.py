"""Optional desktop notifications (macOS osascript / Linux notify-send)."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

logger = logging.getLogger("fae.notifications.desktop")


def send_desktop_notification(title: str, body: str) -> bool:
    """Best-effort local desktop toast. Returns True if a command was invoked."""
    system = platform.system()
    try:
        if system == "Darwin":
            # Escape for AppleScript string literals
            t = title.replace("\\", "\\\\").replace('"', '\\"')
            b = body.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{b}" with title "{t}"'
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                timeout=5,
                capture_output=True,
            )
            return True
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", title, body],
                check=False,
                timeout=5,
                capture_output=True,
            )
            return True
    except Exception:  # noqa: BLE001
        logger.debug("desktop notification failed", exc_info=True)
    return False
