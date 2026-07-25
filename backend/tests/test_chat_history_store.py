"""Tests for the SQLite-backed chat history store."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fae.chat_history import ChatHistoryStore, chat_history_cleanup_loop


def test_append_and_list_round_trip(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history.db", retention_days=7)
    try:
        first = store.append("sess", "你好", "你好呀")
        second = store.append("sess", "今天天气", "晴 25 度")
        store.append("other", "noise", "应当忽略")

        turns = store.list("sess")
        assert [t.user_text for t in turns] == ["你好", "今天天气"]
        assert [t.assistant_text for t in turns] == ["你好呀", "晴 25 度"]
        assert turns[0].created_at <= turns[1].created_at
        assert turns[0].id == first.id
        assert turns[1].id == second.id
    finally:
        store.close()


def test_list_filters_by_session_and_orders_oldest_first(
    tmp_path: Path,
) -> None:
    store = ChatHistoryStore(tmp_path / "history-order.db")
    try:
        store.append("a", "1", "1a")
        store.append("b", "2", "2a")
        store.append("a", "3", "3a")

        turns_a = [t.user_text for t in store.list("a")]
        turns_b = [t.user_text for t in store.list("b")]
        assert turns_a == ["1", "3"]
        assert turns_b == ["2"]
    finally:
        store.close()


def test_delete_expired_removes_old_rows(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-expire.db", retention_days=2)
    try:
        old = store.append(
            "sess",
            "很久以前",
            "那时",
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        old_age = store.append(
            "sess",
            "过去",
            "过去好",
            created_at=datetime.now(UTC) - timedelta(days=5),
        )
        recent = store.append("sess", "最近", "现在好")
        now = datetime.now(UTC)

        deleted = store.delete_expired(now=now)
        assert deleted == 2

        remaining = store.list("sess", now=now)
        ids = {t.id for t in remaining}
        assert old.id not in ids
        assert old_age.id not in ids
        assert recent.id in ids
    finally:
        store.close()


def test_delete_expired_respects_retention_days(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-retain.db", retention_days=3)
    try:
        store.append(
            "sess",
            "六天前",
            "过去",
            created_at=datetime.now(UTC) - timedelta(days=6),
        )
        two_days = store.append(
            "sess",
            "两天前",
            "近期",
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        now = datetime.now(UTC)
        deleted = store.delete_expired(now=now)
        assert deleted == 1
        ids = {t.id for t in store.list("sess", now=now)}
        assert two_days.id in ids
    finally:
        store.close()


def test_list_omits_expired_turns(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-list.db", retention_days=1)
    try:
        store.append(
            "sess",
            "很久之前",
            "应当过滤",
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        recent = store.append("sess", "现在", "保留")
        now = datetime.now(UTC)
        turns = store.list("sess", now=now)
        assert [t.id for t in turns] == [recent.id]
    finally:
        store.close()


def test_list_with_more_paginates_by_before(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-paginate.db", retention_days=7)
    try:
        base = datetime.now(UTC)
        turns = [
            store.append(
                "sess",
                f"u{i}",
                f"a{i}",
                created_at=base - timedelta(minutes=10 - i),
            )
            for i in range(5)
        ]
        page, has_more = store.list_with_more("sess", limit=2)
        assert has_more is True
        assert [t.id for t in page] == [turns[3].id, turns[4].id]
        older_page, older_more = store.list_with_more(
            "sess", limit=2, before=page[0].created_at,
        )
        assert [t.id for t in older_page] == [turns[1].id, turns[2].id]
        assert older_more is True
        oldest, oldest_more = store.list_with_more(
            "sess", limit=2, before=older_page[0].created_at,
        )
        assert [t.id for t in oldest] == [turns[0].id]
        assert oldest_more is False
    finally:
        store.close()


def test_list_sessions_aggregates(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-sessions.db", retention_days=7)
    try:
        store.append("alpha", "hi", "hello", created_at=datetime.now(UTC) - timedelta(minutes=3))
        store.append("beta", "yo", "hey")
        store.append("alpha", "later", "later reply")
        rows = store.list_sessions()
        ids = [row["session_id"] for row in rows]
        assert ids[0] == "alpha"
        assert ids == sorted(ids, key=lambda x: x)
        alpha = next(r for r in rows if r["session_id"] == "alpha")
        beta = next(r for r in rows if r["session_id"] == "beta")
        assert alpha["turn_count"] == 2
        assert beta["turn_count"] == 1
        assert "T" in alpha["last_activity_at"]
    finally:
        store.close()


def test_list_sessions_ignores_expired(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-sessions-exp.db", retention_days=1)
    try:
        store.append(
            "expired",
            "old",
            "old reply",
            created_at=datetime.now(UTC) - timedelta(days=3),
        )
        store.append("fresh", "new", "new reply")
        rows = store.list_sessions()
        ids = [row["session_id"] for row in rows]
        assert "expired" not in ids
        assert "fresh" in ids
    finally:
        store.close()


def test_append_auto_titles_session_once(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-title.db", retention_days=7)
    try:
        store.append("work", "聊聊项目进度", "好的")
        store.append("work", "然后呢", "接下来")
        rows = store.list_sessions()
        row = next(r for r in rows if r["session_id"] == "work")
        assert row["title"] == "聊聊项目进度"
        assert row["pinned"] is False
    finally:
        store.close()


def test_append_truncates_long_titles(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-title-long.db", retention_days=7)
    try:
        long_text = "这是" * 30
        store.append("long", long_text, "ok")
        rows = store.list_sessions()
        row = next(r for r in rows if r["session_id"] == "long")
        assert row["title"].endswith("…")
        assert len(row["title"]) <= 28
    finally:
        store.close()


def test_update_session_title(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-title-edit.db", retention_days=7)
    try:
        store.append("edit", "原始标题", "ok")
        ok = store.update_session_title("edit", "自定义标题")
        assert ok is True
        rows = store.list_sessions()
        row = next(r for r in rows if r["session_id"] == "edit")
        assert row["title"] == "自定义标题"
        assert store.update_session_title("nonexistent", "x") is False
    finally:
        store.close()


def test_set_session_pinned(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-pin.db", retention_days=7)
    try:
        store.append("p", "hi", "hello")
        ok = store.set_session_pinned("p", True)
        assert ok is True
        row = next(r for r in rows if r["session_id"] == "p") if False else None
        rows = store.list_sessions()
        row = next(r for r in rows if r["session_id"] == "p")
        assert row["pinned"] is True
        store.set_session_pinned("p", False)
        rows = store.list_sessions()
        row = next(r for r in rows if r["session_id"] == "p")
        assert row["pinned"] is False
    finally:
        store.close()


def test_delete_expired_skips_pinned(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-pin-cleanup.db", retention_days=2)
    try:
        old_pin = store.append(
            "pinned",
            "重要历史",
            "要保留",
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        old_free = store.append(
            "free",
            "过期聊天",
            "将被清理",
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        recent = store.append("free", "最近的", "保留")
        store.set_session_pinned("pinned", True)
        deleted = store.delete_expired(now=datetime.now(UTC))
        assert deleted == 1
        ids_free = {t.id for t in store.list("free")}
        ids_pinned = {t.id for t in store.list("pinned", limit=10)}
        assert old_free.id not in ids_free
        assert recent.id in ids_free
        assert old_pin.id in ids_pinned
    finally:
        store.close()


@pytest.mark.asyncio
async def test_cleanup_loop_deletes_until_cancelled(tmp_path: Path) -> None:
    store = ChatHistoryStore(tmp_path / "history-cleanup.db", retention_days=1)
    try:
        store.append(
            "sess",
            "过去",
            "丢弃",
            created_at=datetime.now(UTC) - timedelta(days=3),
        )
        store.append("sess", "今", "在")
        task = asyncio.create_task(
            chat_history_cleanup_loop(store, interval_seconds=0.05)
        )

        for _ in range(50):
            await asyncio.sleep(0.05)
            if store.count() == 1:
                break
        assert store.count() == 1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        store.close()
