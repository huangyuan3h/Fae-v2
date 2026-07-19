"""Phase 5.2 — subagent runtime + tool dispatch (FakeProvider, no network)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.agent.subagents.builtins import list_builtin_names
from fae.agent.subagents.runtime import run_subagent
from fae.agent.subagents.tools import dispatch_run_subagent
from fae.agent.known_tools import known_tool_names
from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig
from fae.llm.provider import FakeProvider
from fae.llm.types import ToolCall
from fae.memory.archival import StubArchival
from memory_helpers import make_embedded


def _cfg() -> LLMConfig:
    return LLMConfig(api_key="sk-test", model="fake", base_url="http://test")


def test_known_tools_includes_run_subagent() -> None:
    assert "run_subagent" in known_tool_names()


def test_builtin_names() -> None:
    assert list_builtin_names() == frozenset({"researcher", "coder", "reviewer"})


@pytest.mark.asyncio
async def test_run_subagent_unknown_name() -> None:
    client = LLMClient(provider=FakeProvider(responses=["x"]))
    result = await run_subagent(
        "wizard",
        "do things",
        llm=client,
        config=_cfg(),
    )
    assert not result.ok
    assert result.error == "unknown_name"


@pytest.mark.asyncio
async def test_run_subagent_researcher_and_archival(tmp_path: Path) -> None:
    mem_client, _recall, service = make_embedded(tmp_path, name="sub.db")
    await mem_client.ensure_agent()
    archival = StubArchival()
    service._archival = archival  # type: ignore[attr-defined]

    llm = LLMClient(
        provider=FakeProvider(responses=["要点：本地 TTS 可用 stub 或 Qwen3。"])
    )
    result = await run_subagent(
        "researcher",
        "调研本地 TTS 方案",
        llm=llm,
        config=_cfg(),
        memory=service,
        session_id="default",
    )
    assert result.ok
    assert "TTS" in result.summary or "stub" in result.summary.lower()
    hits = await archival.search("TTS", top_k=5, session_id="default")
    assert hits
    assert any("subagent" in (h.tags or []) for h in hits) or any(
        "subagent" in (getattr(h, "content", "") or "") for h in hits
    )
    # Tag check on stub items
    tagged = [i for i in archival._items if "subagent" in i[6]]  # type: ignore[attr-defined]
    assert tagged
    await mem_client.close()


@pytest.mark.asyncio
async def test_run_subagent_timeout() -> None:
    class SlowProvider(FakeProvider):
        async def chat(self, request):  # type: ignore[no-untyped-def]
            await asyncio.sleep(2)
            return await super().chat(request)

    llm = LLMClient(provider=SlowProvider(responses=["late"]))
    result = await run_subagent(
        "coder",
        "设计一个函数",
        llm=llm,
        config=_cfg(),
        timeout_s=0.05,
    )
    assert not result.ok
    assert result.error == "timeout"


@pytest.mark.asyncio
async def test_dispatch_and_tool_loop(tmp_path: Path) -> None:
    from fae.agent.skills_loader import default_skills_dir

    events: list[dict] = []

    async def on_event(ev: dict) -> None:
        events.append(ev)

    # Probe returns tool call; next chat is subagent body
    provider = FakeProvider(
        responses=["", "调研摘要：三点结论。"],
        tool_call_responses=[
            [
                ToolCall(
                    id="1",
                    name="run_subagent",
                    arguments=json.dumps(
                        {
                            "name": "researcher",
                            "task": "调研 X",
                            "context": "",
                        }
                    ),
                )
            ],
            [],
        ],
    )
    llm = LLMClient(provider=provider)
    req = ChatRequest(
        config=_cfg(),
        messages=[ChatMessage(role="user", content="帮我调研 X")],
    )
    skills = SkillRuntime(
        skills_dir=default_skills_dir(),
        state_path=tmp_path / "skills-state.json",
        enabled=True,
    )
    act = SkillActivationInfo(active=["research_delegate"], tools=[])
    prepared, _act2, early = await apply_lazy_skill_tool(
        llm,
        req,
        act,
        skills,
        subagent_enabled=True,
        on_subagent_event=on_event,
    )
    assert early is None
    assert any(
        "run_subagent" in (m.content or "")
        for m in prepared.messages
        if m.role == "system"
    )
    assert any(e.get("phase") == "start" for e in events)
    assert any(e.get("phase") == "done" and e.get("ok") for e in events)


def test_plain_chat_does_not_attach_subagent_without_skill() -> None:
    from fae.agent.llm_turn import activation_wants_subagent

    act = SkillActivationInfo(active=[], tools=[])
    assert not activation_wants_subagent(act, None)


@pytest.mark.asyncio
async def test_research_delegate_skill_matches(tmp_path: Path) -> None:
    from fae.agent.skills_loader import default_skills_dir

    rt = SkillRuntime(
        skills_dir=default_skills_dir(),
        state_path=tmp_path / "skills-state.json",
        enabled=True,
    )
    act = rt.select("帮我调研一下本地 TTS", session_id="t", record_trigger=False)
    assert "research_delegate" in act.active
    from fae.agent.llm_turn import activation_wants_subagent

    assert activation_wants_subagent(act, rt)


@pytest.mark.asyncio
async def test_run_subagent_empty_task_and_cancel() -> None:
    llm = LLMClient(provider=FakeProvider(responses=["x"]))
    empty = await run_subagent("researcher", "  ", llm=llm, config=_cfg())
    assert not empty.ok
    assert empty.error == "empty_task"

    cancel = asyncio.Event()
    cancel.set()
    cancelled = await run_subagent(
        "reviewer",
        "review this",
        llm=llm,
        config=_cfg(),
        cancel_event=cancel,
    )
    assert not cancelled.ok
    assert cancelled.error == "cancelled"


@pytest.mark.asyncio
async def test_run_subagent_empty_response_and_llm_error() -> None:
    from fae.llm.errors import LLMError

    empty_llm = LLMClient(provider=FakeProvider(responses=[""]))
    empty = await run_subagent(
        "coder", "write a helper", llm=empty_llm, config=_cfg()
    )
    assert not empty.ok
    assert empty.error == "empty_response"

    err_llm = LLMClient(
        provider=FakeProvider(error=LLMError(code="timeout", message="slow"))
    )
    failed = await run_subagent(
        "coder", "write a helper", llm=err_llm, config=_cfg()
    )
    assert not failed.ok
    assert failed.error == "timeout"


@pytest.mark.asyncio
async def test_run_subagent_with_context() -> None:
    llm = LLMClient(provider=FakeProvider(responses=["ok with context"]))
    result = await run_subagent(
        "researcher",
        "topic",
        context="extra notes",
        llm=llm,
        config=_cfg(),
    )
    assert result.ok
    # system + user messages present
    assert llm._provider.calls  # type: ignore[attr-defined]
    user = llm._provider.calls[0].messages[-1].content  # type: ignore[attr-defined]
    assert "extra notes" in user


@pytest.mark.asyncio
async def test_dispatch_bad_json_args() -> None:
    llm = LLMClient(provider=FakeProvider(responses=["unused"]))
    text = await dispatch_run_subagent(
        "{not-json",
        llm=llm,
        config=_cfg(),
    )
    assert "Unknown subagent" in text or "Empty task" in text or "status=failed" in text
