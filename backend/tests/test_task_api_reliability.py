"""HTTP-level tests for Idempotency-Key, progress, and error history."""

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


def _create(
    client: TestClient,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    payload = {"kind": "research", "title": "Look up", **(body or {})}
    resp = client.post("/api/tasks", json=payload, headers=headers or {})
    return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"_status": resp.status_code, "_text": resp.text}


def test_idempotency_key_replays_same_task(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        body = {"kind": "research", "title": "Look up", "payload": {"q": "X"}}
        first = client.post(
            "/api/tasks",
            json=body,
            headers={"Idempotency-Key": "K-1"},
        )
        assert first.status_code == 201, first.text
        first_data = first.json()

        second = client.post(
            "/api/tasks",
            json=body,
            headers={"Idempotency-Key": "K-1"},
        )
        assert second.status_code == 201
        second_data = second.json()
        assert second_data["id"] == first_data["id"]
        assert second_data["idempotency_key"] == "K-1"

        listed = client.get("/api/tasks").json()
        assert sum(1 for t in listed if t.get("idempotency_key") == "K-1") == 1


def test_idempotency_key_with_different_payload_returns_409(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        body1 = {"kind": "research", "title": "Look up", "payload": {"q": "X"}}
        first = client.post(
            "/api/tasks",
            json=body1,
            headers={"Idempotency-Key": "K-2"},
        )
        assert first.status_code == 201

        body2 = {"kind": "research", "title": "Look up", "payload": {"q": "Y"}}
        second = client.post(
            "/api/tasks",
            json=body2,
            headers={"Idempotency-Key": "K-2"},
        )
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["code"] == "idempotency_conflict"
        assert detail["idempotency_key"] == "K-2"


def test_attempts_exhausted_returns_409(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"kind": "k", "title": "t", "max_attempts": 2},
        ).json()
        tid = created["id"]

        # First claim succeeds.
        assert client.post(f"/api/tasks/{tid}/claim", json={}).status_code == 200
        assert client.post(f"/api/tasks/{tid}/fail", json={"error_code": "x"}).status_code == 200
        assert client.post(f"/api/tasks/{tid}/retry", json={}).status_code == 200

        # Second claim succeeds.
        assert client.post(f"/api/tasks/{tid}/claim", json={}).status_code == 200
        assert client.post(f"/api/tasks/{tid}/fail", json={"error_code": "x"}).status_code == 200
        assert client.post(f"/api/tasks/{tid}/retry", json={}).status_code == 200

        # Third claim → exhausted.
        resp = client.post(f"/api/tasks/{tid}/claim", json={})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "attempts_exhausted"
        assert detail["attempts"] == 2
        assert detail["max_attempts"] == 2


def test_progress_endpoint_round_trip(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks", json={"kind": "k", "title": "t"}
        ).json()
        tid = created["id"]
        client.post(f"/api/tasks/{tid}/claim", json={})

        resp = client.patch(
            f"/api/tasks/{tid}/progress",
            json={"progress": {"current": 1, "total": 5, "percent": 20, "current_step": "fetch"}},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["progress"]["current_step"] == "fetch"
        assert data["progress"]["percent"] == 20

        # Second update merges.
        resp = client.patch(
            f"/api/tasks/{tid}/progress",
            json={"progress": {"current_step": "parse", "percent": 40}},
        )
        data = resp.json()
        assert data["progress"]["current"] == 1  # preserved
        assert data["progress"]["current_step"] == "parse"
        assert data["progress"]["percent"] == 40

        # GET includes progress.
        loaded = client.get(f"/api/tasks/{tid}").json()
        assert loaded["progress"]["current_step"] == "parse"


def test_progress_endpoint_rejects_done_with_different_value(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/tasks", json={"kind": "k", "title": "t"}).json()
        tid = created["id"]
        client.post(f"/api/tasks/{tid}/claim", json={})
        client.patch(
            f"/api/tasks/{tid}/progress",
            json={"progress": {"x": 1}},
        )
        client.post(f"/api/tasks/{tid}/complete", json={"result": {"v": 1}})

        # Replay same progress is OK.
        ok = client.patch(
            f"/api/tasks/{tid}/progress",
            json={"progress": {"x": 1}},
        )
        assert ok.status_code == 200

        # Different value → 409.
        bad = client.patch(
            f"/api/tasks/{tid}/progress",
            json={"progress": {"x": 2}},
        )
        assert bad.status_code == 409


def test_fail_appends_error_history(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"kind": "k", "title": "t", "max_attempts": 3},
        ).json()
        tid = created["id"]
        client.post(f"/api/tasks/{tid}/claim", json={})
        client.post(f"/api/tasks/{tid}/fail", json={"error_code": "boom", "error_message": "first"})

        loaded = client.get(f"/api/tasks/{tid}").json()
        assert len(loaded["error_history"]) == 1
        entry = loaded["error_history"][0]
        assert entry["event"] == "attempt_failed"
        assert entry["error_code"] == "boom"
        assert entry["attempt"] == 1

        # Retry, claim again, fail → history accumulates.
        client.post(f"/api/tasks/{tid}/retry", json={})
        client.post(f"/api/tasks/{tid}/claim", json={})
        client.post(f"/api/tasks/{tid}/fail", json={"error_code": "boom2", "error_message": "second"})
        loaded = client.get(f"/api/tasks/{tid}").json()
        assert len(loaded["error_history"]) == 2
        assert loaded["error_history"][1]["error_code"] == "boom2"
        assert loaded["error_history"][1]["attempt"] == 2


def test_retry_clears_stale_error(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks", json={"kind": "k", "title": "t", "max_attempts": 3}
        ).json()
        tid = created["id"]
        client.post(f"/api/tasks/{tid}/claim", json={})
        client.post(f"/api/tasks/{tid}/fail", json={"error_code": "x", "error_message": "old"})

        # Before retry, error is visible.
        loaded = client.get(f"/api/tasks/{tid}").json()
        assert loaded["error_code"] == "x"

        # Retry clears it.
        client.post(f"/api/tasks/{tid}/retry", json={})
        loaded = client.get(f"/api/tasks/{tid}").json()
        assert loaded["status"] == "queued"
        assert loaded["error_code"] is None
        assert loaded["error_message"] is None
        # History preserved.
        assert len(loaded["error_history"]) == 1


def test_duplicate_complete_returns_409_on_mismatch(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/tasks", json={"kind": "k", "title": "t"}).json()
        tid = created["id"]
        client.post(f"/api/tasks/{tid}/claim", json={})
        client.post(f"/api/tasks/{tid}/complete", json={"result": {"v": 1}})

        # Replay same result is OK.
        ok = client.post(f"/api/tasks/{tid}/complete", json={"result": {"v": 1}})
        assert ok.status_code == 200

        # Different result → 409.
        bad = client.post(f"/api/tasks/{tid}/complete", json={"result": {"v": 2}})
        assert bad.status_code == 409