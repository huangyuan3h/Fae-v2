"""Tests for DataDeletionService and store clear() methods."""

from __future__ import annotations

import pytest
from fae.chat_history import ChatHistoryStore
from fae.data_deletion import DataDeletionService
from fae.tool_audit import ToolAuditStore
from fae.agent_trace import AgentTraceStore
from fae.approvals import ApprovalStore
from fae.scheduler.tasks import TaskStore
from fae.scheduler.store import ScheduleStore
from fae.memory.recall_store import RecallStore
from fae.memory.episodic import EpisodicStore
from fae.memory.archival import StubArchival
from fae.agent.tool_offload import ToolOffloader


def _db(p, suffix: str = "") -> str:
    return str(p) + suffix


def test_chat_history_clear_session_scoped(tmp_path) -> None:
    store = ChatHistoryStore(_db(tmp_path, "-chat"))
    try:
        store.append("s1", "hello", "hi")
        store.append("s1", "how are you", "fine")
        store.append("s2", "other", "other-reply")
        assert store.count() == 3

        removed = store.clear(session_id="s1")
        assert removed == 2
        assert store.count() == 1
        assert len(store.list("s2")) == 1

        removed_all = store.clear(session_id=None)
        assert removed_all == 1
        assert store.count() == 0
    finally:
        store.close()


def test_tool_audit_clear_session_scoped(tmp_path) -> None:
    store = ToolAuditStore(_db(tmp_path, "-audit"))
    try:
        store.record_event({"name": "t1", "phase": "done", "ok": True}, session_id="s1", channel="web")
        store.record_event({"name": "t2", "phase": "done", "ok": True}, session_id="s2", channel="web")
        assert len(store.list_events(session_id="s1")) == 1
        assert len(store.list_events(session_id="s2")) == 1

        removed = store.clear(session_id="s1")
        assert removed == 1
        assert len(store.list_events(session_id="s1")) == 0
        assert len(store.list_events(session_id="s2")) == 1

        removed_all = store.clear(session_id=None)
        assert removed_all == 1
        assert store.list_events() == []
    finally:
        store.close()


def test_agent_trace_clear_session_scoped(tmp_path) -> None:
    store = AgentTraceStore(_db(tmp_path, "-trace"))
    try:
        store.record_event({"kind": "tool", "phase": "done", "ok": True, "name": "calc"}, turn_id="t1", session_id="s1", channel="web")
        store.record_event({"kind": "tool", "phase": "done", "ok": True, "name": "calc"}, turn_id="t2", session_id="s2", channel="web")
        assert len(store.list_events(session_id="s1")) == 1
        assert len(store.list_events(session_id="s2")) == 1

        removed = store.clear(session_id="s1")
        assert removed == 1
        assert len(store.list_events(session_id="s1")) == 0
        assert len(store.list_events(session_id="s2")) == 1
    finally:
        store.close()


def test_recall_store_clear_session_scoped(tmp_path) -> None:
    store = RecallStore(_db(tmp_path, "-recall"))
    try:
        store.append("s1", "hello", "hi")
        store.append("s2", "other", "reply")
        assert store.total_hot() == 2

        removed = store.clear(session_id="s1")
        assert removed == 1
        assert store.total_hot() == 1

        removed_all = store.clear(session_id=None)
        assert removed_all == 1
        assert store.total_hot() == 0
    finally:
        store.close()


def test_episodic_store_clear_session_scoped(tmp_path) -> None:
    store = EpisodicStore(_db(tmp_path, "-episodic"))
    try:
        store.add_event(session_id="s1", kind="meeting", summary="Had a meeting")
        store.add_event(session_id="s2", kind="note", summary="A note")
        initial = store.count()
        assert initial >= 2

        removed = store.clear(session_id="s1")
        assert removed > 0

        removed_all = store.clear(session_id=None)
        assert removed_all >= 0
    finally:
        store.close()


def test_archival_stub_clear_session_scoped(tmp_path) -> None:
    archival = StubArchival()

    import asyncio

    async def setup():
        await archival.upsert(text="session-A content", session_id="s1")
        await archival.upsert(text="session-B content", session_id="s2")
        results = await archival.search("session")
        assert len(results) == 2

    asyncio.run(setup())

    async def clear_session():
        return await archival.clear(session_id="s1")

    asyncio.run(clear_session())

    async def search_session_b():
        return await archival.search("session-B")

    results = asyncio.run(search_session_b())
    assert len(results) == 1
    assert results[0].session_id == "s2"

    async def clear_global():
        return await archival.clear(session_id=None)

    asyncio.run(clear_global())

    async def search_empty():
        return await archival.search("")

    results = asyncio.run(search_empty())
    assert len(results) == 0


def test_tool_offloader_clear(tmp_path) -> None:
    offloader = ToolOffloader(str(tmp_path / "offload"))
    assert offloader.clear() == 0


def test_data_deletion_service_forget_session_scoped(tmp_path) -> None:
    chat = ChatHistoryStore(_db(tmp_path, "-chat"))
    audit = ToolAuditStore(_db(tmp_path, "-audit"))
    trace = AgentTraceStore(_db(tmp_path, "-trace"))
    approvals = ApprovalStore(_db(tmp_path, "-approvals"))
    tasks = TaskStore(_db(tmp_path, "-tasks"))
    schedules = ScheduleStore(_db(tmp_path, "-schedules"))
    recall = RecallStore(_db(tmp_path, "-recall"))
    episodic = EpisodicStore(_db(tmp_path, "-episodic"))
    offloader = ToolOffloader(str(tmp_path / "offload"))
    archival = StubArchival()

    chat.append("sess-A", "user-a", "assistant-a")
    chat.append("sess-B", "user-b", "assistant-b")
    audit.record_event({"name": "lookup", "phase": "done", "ok": True}, session_id="sess-A", channel="web")
    audit.record_event({"name": "search", "phase": "done", "ok": True}, session_id="sess-B", channel="web")
    trace.record_event({"kind": "tool", "phase": "done", "ok": True, "name": "calc"}, turn_id="t1", session_id="sess-A", channel="web")
    trace.record_event({"kind": "tool", "phase": "done", "ok": True, "name": "calc"}, turn_id="t2", session_id="sess-B", channel="web")

    service = DataDeletionService(
        chat_history=chat,
        tool_audit=audit,
        agent_trace=trace,
        approvals=approvals,
        task_store=tasks,
        schedule_store=schedules,
        recall_store=recall,
        episodic_store=episodic,
        embedded_memory=None,
        letta_memory=None,
        archival=archival,
        tool_offloader=offloader,
    )

    import asyncio

    result = asyncio.run(service.forget(session_id="sess-A"))

    assert result.global_mode is False
    assert result.session_id == "sess-A"
    assert result.counts["chat_history"] == 1

    assert chat.count() == 1
    remaining = chat.list("sess-B")
    assert len(remaining) == 1
    assert remaining[0].user_text == "user-b"

    chat.close()
    audit.close()
    trace.close()
    approvals.close()
    tasks.close()
    schedules.close()
    recall.close()
    episodic.close()


def test_data_deletion_service_forget_global(tmp_path) -> None:
    chat = ChatHistoryStore(_db(tmp_path, "-chat"))
    audit = ToolAuditStore(_db(tmp_path, "-audit"))
    trace = AgentTraceStore(_db(tmp_path, "-trace"))
    approvals = ApprovalStore(_db(tmp_path, "-approvals"))
    tasks = TaskStore(_db(tmp_path, "-tasks"))
    schedules = ScheduleStore(_db(tmp_path, "-schedules"))
    recall = RecallStore(_db(tmp_path, "-recall"))
    episodic = EpisodicStore(_db(tmp_path, "-episodic"))
    offloader = ToolOffloader(str(tmp_path / "offload"))
    archival = StubArchival()

    chat.append("sess-A", "user-a", "assistant-a")
    chat.append("sess-B", "user-b", "assistant-b")
    audit.record_event({"name": "lookup", "phase": "done", "ok": True}, session_id="sess-A", channel="web")
    audit.record_event({"name": "search", "phase": "done", "ok": True}, session_id="sess-B", channel="web")

    service = DataDeletionService(
        chat_history=chat,
        tool_audit=audit,
        agent_trace=trace,
        approvals=approvals,
        task_store=tasks,
        schedule_store=schedules,
        recall_store=recall,
        episodic_store=episodic,
        embedded_memory=None,
        letta_memory=None,
        archival=archival,
        tool_offloader=offloader,
    )

    import asyncio

    result = asyncio.run(service.forget(session_id=None))

    assert result.global_mode is True
    assert result.session_id is None
    assert result.counts["chat_history"] == 2

    assert chat.count() == 0
    assert audit.list_events() == []
    assert trace.list_events() == []

    chat.close()
    audit.close()
    trace.close()
    approvals.close()
    tasks.close()
    schedules.close()
    recall.close()
    episodic.close()