"""Select and inject active skills into ChatRequest."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from pydantic import BaseModel, Field

from fae.agent.known_tools import known_tool_names
from fae.agent.skills_loader import SkillsLoader, default_skills_dir
from fae.agent.skills_matcher import MatchScore, match_trigger_skills
from fae.agent.skills_schema import LoadStrategy, Skill, SkillMetadata
from fae.agent.skills_state import SkillsStateStore
from fae.llm.types import ChatMessage, ChatRequest

logger = logging.getLogger("fae.agent.skills")

_CHARS_PER_TOKEN = 4

_SKILLS_OPEN = "<active_skills>"
_SKILLS_CLOSE = "</active_skills>"
_LAZY_OPEN = "<available_skills>"
_LAZY_CLOSE = "</available_skills>"

REQUEST_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "request_skill",
        "description": (
            "Load a lazy skill playbook by name when you need specialized guidance. "
            "Only call for names listed in <available_skills>."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to load",
                }
            },
            "required": ["name"],
        },
    },
}


class SkillActivationInfo(BaseModel):
    active: list[str] = Field(default_factory=list)
    lazy_catalog: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)


class SkillRuntime:
    def __init__(
        self,
        *,
        skills_dir: Path | None = None,
        state_path: Path | None = None,
        max_active: int = 2,
        enabled: bool = True,
        repo_root: Path | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_active = max_active
        self.loader = SkillsLoader(skills_dir or default_skills_dir())
        root = repo_root or Path(__file__).resolve().parents[4]
        path = state_path or (root / ".data" / "fae-skills-state.json")
        self.state = SkillsStateStore(path)
        # session_id -> skill_name -> last trigger wall-clock time
        self._cooldown: dict[str, dict[str, float]] = {}

    def list_effective(self) -> list[tuple[Skill, SkillMetadata]]:
        """Return skills with state overlays applied to a copy of meta."""
        out: list[tuple[Skill, SkillMetadata]] = []
        for skill in self.loader.list_skills():
            meta = self._effective_meta(skill)
            out.append((skill, meta))
        return out

    def _effective_meta(self, skill: Skill) -> SkillMetadata:
        overlay = self.state.get(skill.meta.name)
        data = skill.meta.model_dump()
        if "enabled" in overlay:
            data["enabled"] = bool(overlay["enabled"])
        if "requires_approval" in overlay:
            data["requires_approval"] = bool(overlay["requires_approval"])
        return SkillMetadata.model_validate(data)

    def _skills_with_meta(self) -> list[Skill]:
        """Skills whose meta reflects runtime enabled flags."""
        merged: list[Skill] = []
        for skill, meta in self.list_effective():
            merged.append(skill.model_copy(update={"meta": meta}))
        return merged

    def test_trigger(self, text: str) -> list[MatchScore]:
        return match_trigger_skills(text, self._skills_with_meta())

    def _tools_satisfied(self, skill: Skill) -> bool:
        required = [t for t in (skill.meta.requires_tools or []) if t]
        if not required:
            return True
        known = known_tool_names()
        missing = [t for t in required if t not in known]
        if missing:
            logger.warning(
                "skill %s skipped — unknown requires_tools: %s",
                skill.meta.name,
                missing,
            )
            return False
        return True

    @staticmethod
    def _truncate_body(body: str, max_context_tokens: int) -> str:
        text = (body or "").strip()
        if max_context_tokens <= 0:
            return text
        max_chars = max(100, int(max_context_tokens) * _CHARS_PER_TOKEN)
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    def _cooldown_ok(self, session_id: str, skill: Skill, now: float) -> bool:
        cd = skill.meta.cooldown_seconds
        if cd <= 0:
            return True
        last = self._cooldown.get(session_id, {}).get(skill.meta.name)
        if last is None:
            stored = self.state.last_triggered(skill.meta.name)
            last = stored
        if last is None:
            return True
        return (now - last) >= cd

    def _mark_triggered(self, session_id: str, names: list[str], now: float) -> None:
        bucket = self._cooldown.setdefault(session_id, {})
        for name in names:
            bucket[name] = now
            self.state.patch(name, last_triggered_at=now)

    def select(
        self,
        user_text: str,
        *,
        session_id: str = "default",
        manual_names: list[str] | None = None,
        record_trigger: bool = True,
    ) -> SkillActivationInfo:
        if not self.enabled:
            return SkillActivationInfo()

        skills = self._skills_with_meta()
        by_name = {s.meta.name: s for s in skills}
        now = time.time()
        active: list[Skill] = []
        scores: dict[str, float] = {}

        for skill in skills:
            if skill.meta.load_strategy == LoadStrategy.ALWAYS_ON and skill.meta.enabled:
                if not self._tools_satisfied(skill):
                    continue
                if self._cooldown_ok(session_id, skill, now):
                    active.append(skill)
                    scores[skill.meta.name] = 1.0

        # Empty text (Daily seed): never match trigger skills — always_on only.
        matches = (
            match_trigger_skills(user_text, skills)
            if (user_text or "").strip()
            else []
        )
        for m in matches:
            skill = by_name.get(m.name)
            if skill is None or not skill.meta.enabled:
                continue
            if skill.meta.requires_approval:
                continue
            if not self._tools_satisfied(skill):
                continue
            if not self._cooldown_ok(session_id, skill, now):
                continue
            scores[m.name] = m.score
            if skill not in active:
                active.append(skill)

        for name in manual_names or []:
            skill = by_name.get(name)
            if (
                skill
                and skill.meta.enabled
                and skill.meta.load_strategy == LoadStrategy.MANUAL
                and skill not in active
            ):
                active.append(skill)
                scores[name] = scores.get(name, 0.5)

        always = [s for s in active if s.meta.load_strategy == LoadStrategy.ALWAYS_ON]
        others = [s for s in active if s.meta.load_strategy != LoadStrategy.ALWAYS_ON]
        others.sort(
            key=lambda s: (-s.meta.priority, -scores.get(s.meta.name, 0.0), s.meta.name)
        )
        # always_on always included; up to max_active trigger/manual skills
        selected = always + others[: self.max_active]
        seen: set[str] = set()
        final: list[Skill] = []
        for s in selected:
            if s.meta.name in seen:
                continue
            seen.add(s.meta.name)
            final.append(s)

        lazy_catalog = [
            s.meta.name
            for s in skills
            if s.meta.load_strategy == LoadStrategy.LAZY and s.meta.enabled
        ]

        names = [s.meta.name for s in final]
        if names and record_trigger:
            self._mark_triggered(session_id, names, now)

        tools: list[dict] = []
        if lazy_catalog:
            tools = [REQUEST_SKILL_TOOL]

        return SkillActivationInfo(
            active=names,
            lazy_catalog=lazy_catalog,
            scores={k: scores[k] for k in names if k in scores},
            tools=tools,
        )

    def build_system_block(
        self,
        activation: SkillActivationInfo,
        *,
        include_lazy_catalog: bool = True,
    ) -> str | None:
        skills = {s.meta.name: s for s in self._skills_with_meta()}
        parts: list[str] = []
        if activation.active:
            bodies: list[str] = []
            for name in activation.active:
                skill = skills.get(name)
                if not skill:
                    continue
                body = self._truncate_body(
                    skill.body, skill.meta.max_context_tokens
                )
                bodies.append(f"### skill:{name}\n{body}\n")
            if bodies:
                parts.append(
                    f"{_SKILLS_OPEN}\n"
                    "Follow these playbooks when relevant to the user turn.\n"
                    + "\n".join(bodies)
                    + f"{_SKILLS_CLOSE}"
                )
        if include_lazy_catalog and activation.lazy_catalog:
            lines = []
            for name in activation.lazy_catalog:
                skill = skills.get(name)
                desc = skill.meta.description if skill else ""
                lines.append(f"- {name}: {desc}")
            parts.append(
                f"{_LAZY_OPEN}\n"
                "You may call request_skill(name) once to load one of:\n"
                + "\n".join(lines)
                + f"\n{_LAZY_CLOSE}"
            )
        if not parts:
            return None
        return "\n\n".join(parts)

    def inject(
        self,
        request: ChatRequest,
        activation: SkillActivationInfo,
        *,
        include_lazy_catalog: bool = True,
    ) -> ChatRequest:
        block = self.build_system_block(
            activation, include_lazy_catalog=include_lazy_catalog
        )
        if not block:
            return request
        # Insert after leading system messages (e.g. memory) so memory stays first.
        messages = list(request.messages)
        idx = 0
        while idx < len(messages) and messages[idx].role == "system":
            idx += 1
        skill_msg = ChatMessage(role="system", content=block)
        messages = [*messages[:idx], skill_msg, *messages[idx:]]
        return request.model_copy(update={"messages": messages})

    def prepare_request(
        self,
        request: ChatRequest,
        *,
        session_id: str = "default",
        user_text: str | None = None,
    ) -> tuple[ChatRequest, SkillActivationInfo]:
        text = user_text
        if text is None:
            for msg in reversed(request.messages):
                if msg.role == "user":
                    text = msg.content
                    break
        activation = self.select(text or "", session_id=session_id)
        return self.inject(request, activation), activation

    def activate(
        self,
        names: list[str],
        *,
        session_id: str = "default",
        respect_cooldown: bool = True,
        record_trigger: bool = True,
    ) -> SkillActivationInfo:
        """Force-activate skills by name (Phase 4 cron / proactive).

        Ignores ``load_strategy`` so lazy skills (e.g. proactive_outreach)
        can be injected without waiting for ``request_skill``.
        """
        if not self.enabled:
            return SkillActivationInfo()
        skills = self._skills_with_meta()
        by_name = {s.meta.name: s for s in skills}
        now = time.time()
        active: list[Skill] = []
        scores: dict[str, float] = {}
        for name in names:
            skill = by_name.get(name)
            if skill is None or not skill.meta.enabled:
                continue
            if skill.meta.requires_approval:
                continue
            if respect_cooldown and not self._cooldown_ok(session_id, skill, now):
                continue
            if skill not in active:
                active.append(skill)
                scores[name] = 1.0
        final_names = [s.meta.name for s in active]
        if final_names and record_trigger:
            self._mark_triggered(session_id, final_names, now)
        return SkillActivationInfo(
            active=final_names,
            lazy_catalog=[],
            scores=scores,
            tools=[],
        )

    def prepare_activated_request(
        self,
        request: ChatRequest,
        names: list[str],
        *,
        session_id: str = "default",
        respect_cooldown: bool = True,
    ) -> tuple[ChatRequest, SkillActivationInfo]:
        """Inject force-activated skills into a ChatRequest (Phase 4)."""
        activation = self.activate(
            names,
            session_id=session_id,
            respect_cooldown=respect_cooldown,
        )
        return self.inject(request, activation, include_lazy_catalog=False), activation

    def load_lazy_into_request(
        self,
        request: ChatRequest,
        skill_name: str,
        activation: SkillActivationInfo,
        *,
        session_id: str = "default",
        respect_cooldown: bool = True,
    ) -> tuple[ChatRequest, SkillActivationInfo]:
        """Add a lazy skill body and drop tools catalog for the final stream."""
        skill = self.loader.get(skill_name)
        if skill is None:
            return request, activation
        meta = self._effective_meta(skill)
        if not meta.enabled or meta.load_strategy != LoadStrategy.LAZY:
            return request, activation
        now = time.time()
        # Use effective meta so cooldown overlays apply.
        skill_eff = skill.model_copy(update={"meta": meta})
        if respect_cooldown and not self._cooldown_ok(session_id, skill_eff, now):
            return request, activation
        new_active = list(activation.active)
        if skill_name not in new_active:
            new_active.append(skill_name)
        new_info = SkillActivationInfo(
            active=new_active,
            lazy_catalog=[],
            scores={**activation.scores, skill_name: 1.0},
            tools=[],
        )
        self._mark_triggered(session_id, [skill_name], now)
        # Strip prior skill system messages then re-inject
        messages = [
            m
            for m in request.messages
            if not (
                m.role == "system"
                and (
                    _SKILLS_OPEN in m.content
                    or _LAZY_OPEN in m.content
                )
            )
        ]
        stripped = request.model_copy(update={"messages": messages})
        return self.inject(stripped, new_info, include_lazy_catalog=False), new_info

    def system_message_dict(
        self,
        user_text: str,
        session_id: str,
        *,
        record_trigger: bool = False,
    ) -> dict[str, str] | None:
        """Build a skill system message for Daily LLMContext.

        Seed calls use empty ``user_text`` (always_on + lazy catalog only).
        Per-turn rematch passes real user text with ``record_trigger=True``.
        """
        activation = self.select(
            user_text,
            session_id=session_id,
            record_trigger=record_trigger,
        )
        block = self.build_system_block(activation, include_lazy_catalog=True)
        if not block:
            return None
        return {"role": "system", "content": block}

    def refresh_context_skills(
        self,
        context: object,
        user_text: str,
        *,
        session_id: str = "default",
    ) -> list[str]:
        """Replace FAE skill system messages on a Pipecat LLMContext."""
        text = (user_text or "").strip()
        activation = self.select(
            text,
            session_id=session_id,
            record_trigger=bool(text),
        )
        block = self.build_system_block(activation, include_lazy_catalog=True)
        msg = (
            {"role": "system", "content": block} if block else None
        )
        get_messages = getattr(context, "get_messages", None)
        set_messages = getattr(context, "set_messages", None)
        if not callable(get_messages) or not callable(set_messages):
            return list(activation.active)
        existing = list(get_messages())
        kept = [
            m
            for m in existing
            if not (
                isinstance(m, dict)
                and m.get("role") == "system"
                and isinstance(m.get("content"), str)
                and (
                    _SKILLS_OPEN in m["content"] or _LAZY_OPEN in m["content"]
                )
            )
        ]
        if msg is not None:
            # Keep memory/persona system messages first; skills after them.
            insert_at = 0
            for i, m in enumerate(kept):
                if isinstance(m, dict) and m.get("role") == "system":
                    insert_at = i + 1
                else:
                    break
            kept = [*kept[:insert_at], msg, *kept[insert_at:]]
        set_messages(kept)
        return list(activation.active)
