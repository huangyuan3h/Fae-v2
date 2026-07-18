"""Pydantic schemas for Phase 2 memory APIs (2.1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FactIn(BaseModel):
    """Structured fact to persist into Letta / archival memory."""

    content: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None


class FactOut(BaseModel):
    id: str
    content: str
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    created_at: datetime | None = None


class UserProfile(BaseModel):
    """Core-memory user block snapshot."""

    display_name: str | None = None
    preferences: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class RecallTurn(BaseModel):
    """One user/assistant exchange in session recall."""

    id: str
    session_id: str
    user_text: str
    assistant_text: str
    created_at: datetime | None = None
