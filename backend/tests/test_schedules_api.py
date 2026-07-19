"""Phase 4 schedules REST API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae import config as config_module
from fae.api import create_app
from fae.scheduler.parse_nl import parse_schedule_text


def test_parse_tomorrow_vitamin() -> None:
    parsed = parse_schedule_text("明早8点提醒吃维生素")
    assert parsed.kind == "date"
    assert parsed.run_at is not None
    assert "维生素" in parsed.title or "维生素" in parsed.body


def test_parse_daily_cron() -> None:
    parsed = parse_schedule_text("每天9点喝水")
    assert parsed.kind == "cron"
    assert parsed.cron == "0 9 * * *"


def test_schedules_crud(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "s.db"))
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())

    listed = client.get("/api/schedules")
    assert listed.status_code == 200
    assert "jobs" in listed.json()

    created = client.post(
        "/api/schedules",
        json={"text": "明早8点提醒吃维生素"},
    )
    assert created.status_code == 200
    job = created.json()
    assert job["kind"] == "date"
    job_id = job["id"]

    patched = client.patch(f"/api/schedules/{job_id}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    triggered = client.post(f"/api/schedules/{job_id}/trigger")
    assert triggered.status_code == 200

    inbox = client.get("/api/notifications")
    assert inbox.status_code == 200
    assert len(inbox.json()["items"]) >= 1

    deleted = client.delete(f"/api/schedules/{job_id}")
    assert deleted.status_code == 200


def test_schedules_parse_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "s.db"))
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/api/schedules/parse", json={"text": "每天8点起床"})
    assert resp.status_code == 200
    assert resp.json()["cron"] == "0 8 * * *"
