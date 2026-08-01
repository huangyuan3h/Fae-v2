"""Tests for the Plan Mode HTTP surface (`/api/plans/*`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.agent.plan_tools import dispatch_update_plan
from fae.api import create_app
from fae.config import get_settings
from fae.plans import PlanStore


@pytest.fixture()
def client(tmp_path: Path):
    settings = get_settings()
    settings.plans_db_path = str(tmp_path / "plans.db")
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


def _create_plan(client: TestClient, session_id: str = "s1") -> None:
    store: PlanStore = client.app.state.plan_store
    dispatch_update_plan(
        {
            "action": "create",
            "title": "ship",
            "summary": "release",
            "steps": [{"title": "build"}, {"title": "deploy"}],
        },
        session_id=session_id,
        plan_store=store,
    )


def test_get_active_returns_plan(client: TestClient) -> None:
    _create_plan(client)
    res = client.get("/api/plans/active", params={"session_id": "s1"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["session_id"] == "s1"
    assert payload["plan"]["title"] == "ship"
    assert len(payload["plan"]["steps"]) == 2


def test_get_active_returns_null_for_missing_session(client: TestClient) -> None:
    res = client.get("/api/plans/active", params={"session_id": "absent"})
    assert res.status_code == 200
    assert res.json() == {"plan": None, "session_id": "absent"}


def test_abandon_active_plan(client: TestClient) -> None:
    _create_plan(client)
    store: PlanStore = client.app.state.plan_store
    plan = store.get_active_for_session("s1")
    res = client.post(f"/api/plans/{plan.id}/abandon")
    assert res.status_code == 200
    assert res.json() == {"plan_id": plan.id, "status": "abandoned"}
    assert store.get_active_for_session("s1") is None


def test_abandon_unknown_plan_returns_404(client: TestClient) -> None:
    res = client.post("/api/plans/does-not-exist/abandon")
    assert res.status_code == 404