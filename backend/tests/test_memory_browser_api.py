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
        assert patched.json()["id"] == fact_id
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


def test_facts_404_and_search_requires_q(tmp_path: Path) -> None:
    with _app(tmp_path) as http:
        missing = http.patch(
            "/api/memory/facts/does-not-exist",
            json={"content": "x", "tags": []},
        )
        assert missing.status_code == 404

        gone = http.delete("/api/memory/facts/does-not-exist")
        assert gone.status_code == 404

        bad = http.get("/api/memory/search", params={"q": ""})
        assert bad.status_code == 400


def test_persona_get_put_and_reset(tmp_path: Path) -> None:
    with _app(tmp_path) as http:
        got = http.get("/api/memory/persona")
        assert got.status_code == 200
        body = got.json()
        assert body["persona"]
        assert body["default"]
        assert len(body["presets"]) >= 3
        assert {p["id"] for p in body["presets"]} >= {"warm", "concise", "advisor"}

        empty = http.put("/api/memory/persona", json={})
        assert empty.status_code == 400

        blank = http.put("/api/memory/persona", json={"persona": "   "})
        assert blank.status_code == 400

        custom = "You are FAE. Always greet with a gentle check-in."
        saved = http.put("/api/memory/persona", json={"persona": custom})
        assert saved.status_code == 200
        assert saved.json()["persona"] == custom

        again = http.get("/api/memory/persona")
        assert again.status_code == 200
        assert again.json()["persona"] == custom

        reset = http.put("/api/memory/persona", json={"reset": True})
        assert reset.status_code == 200
        assert reset.json()["persona"] == reset.json()["default"]

        # Persona and human stay independent
        http.put(
            "/api/memory/profile",
            json={"human": "Name: 小明\nLives in 北京."},
        )
        persona_after = http.get("/api/memory/persona")
        assert persona_after.json()["persona"] == persona_after.json()["default"]
        profile = http.get("/api/memory/profile")
        assert "小明" in profile.json()["human"]


def test_profile_get_and_put(tmp_path: Path) -> None:
    with _app(tmp_path) as http:
        empty = http.put("/api/memory/profile", json={})
        assert empty.status_code == 400

        saved = http.put(
            "/api/memory/profile",
            json={
                "human": "Name: 小明\nLives in 北京.\nTimezone: Asia/Shanghai\n喜欢简洁回答。"
            },
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["display_name"] == "小明"
        assert body["city"] == "北京"
        assert body["timezone"] == "Asia/Shanghai"
        assert "Lives in 北京." in body["human"]

        got = http.get("/api/memory/profile")
        assert got.status_code == 200
        assert got.json()["city"] == "北京"

        # Correction via freeform replace
        updated = http.put(
            "/api/memory/profile",
            json={"human": "Name: 小明\nLives in 上海.\n喜欢简洁回答。"},
        )
        assert updated.status_code == 200
        assert updated.json()["city"] == "上海"
        assert updated.json()["display_name"] == "小明"

        # Field upsert still writes freeform Lives in …
        via_city = http.put("/api/memory/profile", json={"city": "杭州"})
        assert via_city.status_code == 200
        assert via_city.json()["city"] == "杭州"
        assert "Lives in 杭州." in via_city.json()["human"]
