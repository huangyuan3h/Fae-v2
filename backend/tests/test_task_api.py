from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings


def _build_app(tmp_path) -> tuple[Any, Settings]:
    settings = Settings(
        letta_mode="off",
        scheduler_enabled=False,
        tool_audit_db_path=str(tmp_path / "audit.db"),
        agent_trace_db_path=str(tmp_path / "trace.db"),
        task_db_path=str(tmp_path / "tasks.db"),
    )
    return create_app(settings=settings), settings


def _create(client: TestClient, **overrides: Any) -> dict:
    body = {"kind": "research", "title": "Look up", **overrides}
    resp = client.post("/api/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_tasks(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client, session_id="alpha")
        assert created["status"] == "queued"
        assert created["attempts"] == 0
        listed = client.get("/api/tasks", params={"session_id": "alpha"}).json()
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]
        summary = client.get(
            "/api/tasks/summary", params={"session_id": "alpha"}
        ).json()
        assert summary["queued"] == 1


def test_full_lifecycle_with_needs_input(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client)
        task_id = created["id"]

        claim = client.post(
            f"/api/tasks/{task_id}/claim", json={"note": "started"}
        )
        assert claim.status_code == 200
        assert claim.json()["status"] == "running"
        assert claim.json()["attempts"] == 1

        ask = client.post(
            f"/api/tasks/{task_id}/needs-input",
            json={"prompt": "需要城市", "context": {"known": False}},
        )
        assert ask.status_code == 200
        body = ask.json()
        assert body["status"] == "needs_input"
        assert body["resume_token"]["prompt"] == "需要城市"
        assert body["resume_token"]["context"] == {"known": False}

        back = client.post(
            f"/api/tasks/{task_id}/provide-input",
            json={"input": {"city": "上海"}},
        )
        assert back.status_code == 200
        assert back.json()["status"] == "running"
        assert back.json()["resume_token"]["input"] == {"city": "上海"}

        done = client.post(
            f"/api/tasks/{task_id}/complete",
            json={"result": {"answer": "OK"}, "note": "finished"},
        )
        assert done.status_code == 200
        final = done.json()
        assert final["status"] == "done"
        assert final["result"] == {"answer": "OK"}
        assert final["is_terminal"] is True


def test_invalid_transition_returns_409(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client)
        task_id = created["id"]
        resp = client.post(
            f"/api/tasks/{task_id}/complete",
            json={"result": {"early": True}},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_transition"
        assert detail["from"] == "queued"
        assert detail["to"] == "done"


def test_retry_flow(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client, max_attempts=2)
        task_id = created["id"]
        client.post(f"/api/tasks/{task_id}/claim", json={})
        fail = client.post(
            f"/api/tasks/{task_id}/fail",
            json={"error_code": "boom", "error_message": "kaboom"},
        )
        assert fail.status_code == 200
        assert fail.json()["status"] == "failed"
        retry = client.post(f"/api/tasks/{task_id}/retry", json={"note": "try 2"})
        assert retry.status_code == 200
        assert retry.json()["status"] == "queued"
        running = client.post(f"/api/tasks/{task_id}/claim", json={})
        assert running.json()["attempts"] == 2
        second_done = client.post(
            f"/api/tasks/{task_id}/complete", json={"result": {"ok": True}}
        )
        assert second_done.json()["status"] == "done"


def test_cancel_then_retry(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client)
        task_id = created["id"]
        cancel = client.post(
            f"/api/tasks/{task_id}/cancel",
            json={"note": "user abort"},
        )
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"
        # Already cancelled → cancel succeeds (no-op).
        again = client.post(f"/api/tasks/{task_id}/cancel", json={})
        assert again.status_code == 200
        # Retry from cancelled works.
        retry = client.post(f"/api/tasks/{task_id}/retry", json={})
        assert retry.status_code == 200
        assert retry.json()["status"] == "queued"


def test_get_unknown_task_returns_404(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/api/tasks/does-not-exist")
        assert resp.status_code == 404


def test_status_filter_validation(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/api/tasks", params={"status": "bogus"})
        assert resp.status_code == 400


def test_list_paginates_with_before(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = [
            _create(client, title=f"task-{i}") for i in range(3)
        ]
        cursor = created[1]["updated_at"]
        earlier = client.get(
            "/api/tasks",
            params={"before": cursor, "limit": 10},
        ).json()
        ids_earlier = [t["id"] for t in earlier]
        assert created[0]["id"] in ids_earlier
        assert created[1]["id"] not in ids_earlier
        assert created[2]["id"] not in ids_earlier


def test_recovery_on_lifespan_startup(tmp_path) -> None:
    """Restart the app while a task is left ``running`` — recovery should
    promote it to ``needs_input``."""
    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        created = _create(client)
        task_id = created["id"]
        client.post(f"/api/tasks/{task_id}/claim", json={})
        assert client.get(f"/api/tasks/{task_id}").json()["status"] == "running"

    new_app = create_app(settings=settings)
    with TestClient(new_app) as client:
        loaded = client.get(f"/api/tasks/{task_id}").json()
        assert loaded["status"] == "needs_input"
        assert loaded["result"]["resume_reason"] == "service_restart"
        # claim bumped attempts to 1; recovery increments to 2.
        assert loaded["attempts"] == 2


def test_api_returns_empty_when_store_missing(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        app.state.task_store = None
        resp = client.get("/api/tasks")
        # store missing → 503 from each handler
        assert resp.status_code == 503
