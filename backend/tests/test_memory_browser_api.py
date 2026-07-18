"""Phase 2.5 — facts CRUD + search/timeline APIs."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient


def _app(tmp_path: Path) -> TestClient:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "m.db"),
        recall_db_path=str(tmp_path / "r.db"),
        episodic_db_path=str(tmp_path / "e.db"),
        archival_prefer_stub=True,
        sleeptime_enabled=False,
    )
    app = create_app(
        settings=settings,
        llm_client=LLMClient(provider=FakeProvider(tokens=["x"])),
    )
    return TestClient(app)


def test_facts_crud_and_search(tmp_path: Path) -> None:
    with _app(tmp_path) as http:
        created = http.post(
            "/api/memory/facts",
            json={"content": "User likes pour-over coffee", "tags": ["pref"]},
        )
        assert created.status_code == 200
        fact_id = created.json()["id"]

        listed = http.get("/api/memory/facts")
        assert listed.status_code == 200
        assert any(f["id"] == fact_id for f in listed.json()["facts"])

        patched = http.patch(
            f"/api/memory/facts/{fact_id}",
            json={"content": "User likes espresso", "tags": ["pref"]},
        )
        assert patched.status_code == 200
        assert "espresso" in patched.json()["content"]

        search = http.get("/api/memory/search", params={"q": "espresso"})
        assert search.status_code == 200
        body = search.json()
        assert body["facts"] or body["archival"] or body["events"] is not None

        timeline = http.get("/api/memory/timeline")
        assert timeline.status_code == 200
        assert "points" in timeline.json()

        deleted = http.delete(f"/api/memory/facts/{fact_id}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True
