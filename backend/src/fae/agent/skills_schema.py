"""Skill metadata and loaded skill documents."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class LoadStrategy(str, Enum):
    ALWAYS_ON = "always_on"
    TRIGGER_BASED = "trigger_based"
    MANUAL = "manual"
    LAZY = "lazy"


class SkillMetadata(BaseModel):
    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=0, le=10)
    max_context_tokens: int = Field(default=1000, ge=100)
    enabled: bool = True
    requires_approval: bool = False
    cooldown_seconds: int = Field(default=0, ge=0)
    load_strategy: LoadStrategy = LoadStrategy.TRIGGER_BASED


class Skill(BaseModel):
    meta: SkillMetadata
    body: str
    path: Path | None = None
    raw_markdown: str = ""

    model_config = {"arbitrary_types_allowed": True}
