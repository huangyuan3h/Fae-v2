"""HTTP API for Skill playbooks (Phase 3)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from fae.agent.skills_runtime import SkillRuntime

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _runtime(request: Request) -> SkillRuntime:
    skills = getattr(request.app.state, "skills", None)
    if not isinstance(skills, SkillRuntime):
        raise HTTPException(status_code=503, detail="skills runtime not ready")
    return skills


class SkillListItem(BaseModel):
    name: str
    description: str
    load_strategy: str
    priority: int
    enabled: bool
    requires_approval: bool
    cooldown_seconds: int
    triggers: list[str]
    last_triggered_at: float | None = None


class SkillDetail(SkillListItem):
    body: str
    raw_markdown: str
    requires_tools: list[str] = Field(default_factory=list)
    max_context_tokens: int = 1000


class SkillPatch(BaseModel):
    enabled: bool | None = None
    requires_approval: bool | None = None


class SkillPut(BaseModel):
    markdown: str = Field(min_length=1)


class TestTriggerIn(BaseModel):
    text: str = Field(min_length=1)


class TestTriggerOut(BaseModel):
    matches: list[dict[str, Any]]
    active: list[str]


@router.get("", response_model=list[SkillListItem])
async def list_skills(skills: Annotated[SkillRuntime, Depends(_runtime)]) -> list[SkillListItem]:
    items: list[SkillListItem] = []
    for skill, meta in skills.list_effective():
        st = skills.state.get(meta.name)
        last = st.get("last_triggered_at")
        items.append(
            SkillListItem(
                name=meta.name,
                description=meta.description,
                load_strategy=meta.load_strategy.value,
                priority=meta.priority,
                enabled=meta.enabled,
                requires_approval=meta.requires_approval,
                cooldown_seconds=meta.cooldown_seconds,
                triggers=list(meta.triggers),
                last_triggered_at=float(last) if isinstance(last, (int, float)) else None,
            )
        )
    return items


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(
    name: str, skills: Annotated[SkillRuntime, Depends(_runtime)]
) -> SkillDetail:
    found = None
    meta = None
    for skill, m in skills.list_effective():
        if m.name == name:
            found, meta = skill, m
            break
    if found is None or meta is None:
        raise HTTPException(status_code=404, detail="skill not found")
    st = skills.state.get(name)
    last = st.get("last_triggered_at")
    return SkillDetail(
        name=meta.name,
        description=meta.description,
        load_strategy=meta.load_strategy.value,
        priority=meta.priority,
        enabled=meta.enabled,
        requires_approval=meta.requires_approval,
        cooldown_seconds=meta.cooldown_seconds,
        triggers=list(meta.triggers),
        last_triggered_at=float(last) if isinstance(last, (int, float)) else None,
        body=found.body,
        raw_markdown=found.raw_markdown or found.body,
        requires_tools=list(meta.requires_tools),
        max_context_tokens=meta.max_context_tokens,
    )


@router.put("/{name}", response_model=SkillDetail)
async def put_skill(
    name: str,
    body: SkillPut,
    skills: Annotated[SkillRuntime, Depends(_runtime)],
) -> SkillDetail:
    try:
        skills.loader.write_skill(name, body.markdown)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await get_skill(name, skills)


@router.patch("/{name}", response_model=SkillListItem)
async def patch_skill(
    name: str,
    body: SkillPatch,
    skills: Annotated[SkillRuntime, Depends(_runtime)],
) -> SkillListItem:
    if skills.loader.get(name) is None:
        raise HTTPException(status_code=404, detail="skill not found")
    skills.state.patch(
        name,
        enabled=body.enabled,
        requires_approval=body.requires_approval,
    )
    for item in await list_skills(skills):
        if item.name == name:
            return item
    raise HTTPException(status_code=404, detail="skill not found")


@router.post("/test-trigger", response_model=TestTriggerOut)
async def test_trigger(
    body: TestTriggerIn,
    skills: Annotated[SkillRuntime, Depends(_runtime)],
) -> TestTriggerOut:
    matches = skills.test_trigger(body.text)
    activation = skills.select(
        body.text, session_id="__test_trigger__", record_trigger=False
    )
    return TestTriggerOut(
        matches=[{"name": m.name, "score": m.score} for m in matches],
        active=activation.active,
    )
