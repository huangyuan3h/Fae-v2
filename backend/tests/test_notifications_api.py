"""Phase 4 notifications API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae import config as config_module
from fae.api import create_app
from fae.scheduler.delivery import _in_quiet_hours


def test_quiet_hours_wrap() -> None:
    assert _in_quiet_hours(22, 7, now_hour=23)
    assert _in_quiet_hours(22, 7, now_hour=3)
    assert not _in_quiet_hours(22, 7, now_hour=12)
    assert _in_quiet_hours(1, 5, now_hour=2)
    assert not _in_quiet_hours(None, None, now_hour=2)


def test_prefs_and_subscribe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "n.db"))
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())

    prefs = client.get("/api/notifications/prefs")
    assert prefs.status_code == 200
    assert prefs.json()["enabled"] is True

    updated = client.put(
        "/api/notifications/prefs",
        json={
            "enabled": True,
            "quiet_start_hour": 22,
            "quiet_end_hour": 7,
            "desktop_enabled": False,
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["quiet_start_hour"] == 22
    assert body["desktop_enabled"] is False

    sub = client.post(
        "/api/notifications/subscribe",
        json={
            "endpoint": "https://example.com/push/1",
            "keys": {"p256dh": "abc", "auth": "def"},
        },
    )
    assert sub.status_code == 200

    vapid = client.get("/api/notifications/vapid-public-key")
    assert vapid.status_code == 404

    unsub = client.request(
        "DELETE",
        "/api/notifications/subscribe",
        json={
            "endpoint": "https://example.com/push/1",
            "keys": {"p256dh": "abc", "auth": "def"},
        },
    )
    assert unsub.status_code == 200
