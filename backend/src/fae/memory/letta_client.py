"""Letta REST client (Phase 2.1).

Talks to a self-hosted Letta server over HTTP. Callers should treat all
methods as best-effort: raise on hard failures so the service layer can
log and degrade without breaking chat.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from fae.memory.core_budget import clip_current_for_prompt, truncate_current
from fae.memory.defaults import DEFAULT_CURRENT, DEFAULT_HUMAN, DEFAULT_PERSONA
from fae.memory.recall_store import RecallStore
from fae.memory.schemas import FactIn, FactOut, RecallTurn, UserProfile

logger = logging.getLogger("fae.memory.letta")

MEMORY_TOOLS: tuple[str, ...] = (
    "memory_save_fact",
    "memory_search",
    "memory_update_user",
)


def memory_tool_stubs() -> list[dict[str, Any]]:
    """OpenAI-style tool definitions for future agent registration."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"FAE memory tool: {name}",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in MEMORY_TOOLS
    ]


class LettaMemoryClient:
    """Thin async wrapper around Letta's HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        agent_name: str = "fae-main",
        api_key: str | None = None,
        model: str = "openai/gpt-4o-mini",
        embedding: str = "openai/text-embedding-3-small",
        timeout_s: float = 15.0,
        recall_store: RecallStore | None = None,
        current_char_limit: int = 2000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_name = agent_name
        self.model = model
        self.embedding = embedding
        self._agent_id: str | None = None
        self._recall = recall_store
        self._current_char_limit = current_char_limit
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout_s,
        )

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    async def ensure_agent(self) -> str:
        """Create or resolve the named agent; return agent_id."""
        existing = await self._find_agent_id()
        if existing:
            self._agent_id = existing
            logger.info("Letta agent resolved name=%s id=%s", self.agent_name, existing)
            return existing

        payload: dict[str, Any] = {
            "name": self.agent_name,
            "memory_blocks": [
                {"label": "persona", "value": DEFAULT_PERSONA, "limit": 5000},
                {"label": "human", "value": DEFAULT_HUMAN, "limit": 5000},
                {"label": "current", "value": DEFAULT_CURRENT, "limit": 5000},
            ],
            "model": self.model,
            "embedding": self.embedding,
        }
        resp = await self._http.post("/v1/agents/", json=payload)
        if resp.status_code >= 400:
            # Retry without embedding (some servers derive it).
            payload.pop("embedding", None)
            resp = await self._http.post("/v1/agents/", json=payload)
        resp.raise_for_status()
        data = resp.json()
        agent_id = data.get("id") or data.get("agent_id")
        if not agent_id:
            raise RuntimeError(f"Letta create agent missing id: {data!r}")
        self._agent_id = str(agent_id)
        logger.info("Letta agent created name=%s id=%s", self.agent_name, agent_id)
        return self._agent_id

    async def _find_agent_id(self) -> str | None:
        # Prefer name query when supported; fall back to list scan.
        for path in (f"/v1/agents/?name={self.agent_name}", "/v1/agents/"):
            try:
                resp = await self._http.get(path)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400:
                continue
            data = resp.json()
            agents = data if isinstance(data, list) else data.get("agents") or data.get("items") or []
            if not isinstance(agents, list):
                continue
            for agent in agents:
                if not isinstance(agent, dict):
                    continue
                if agent.get("name") == self.agent_name:
                    aid = agent.get("id") or agent.get("agent_id")
                    if aid:
                        return str(aid)
            # name-filtered endpoint may return a single match list
            if "name=" in path and len(agents) == 1 and isinstance(agents[0], dict):
                aid = agents[0].get("id") or agents[0].get("agent_id")
                if aid:
                    return str(aid)
        return None

    def _require_agent(self) -> str:
        if not self._agent_id:
            raise RuntimeError("ensure_agent() must be called first")
        return self._agent_id

    async def _get_block(self, label: str) -> str:
        agent_id = self._require_agent()
        resp = await self._http.get(
            f"/v1/agents/{agent_id}/core-memory/blocks/{label}"
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("value") or "")

    async def _set_block(self, label: str, value: str) -> None:
        agent_id = self._require_agent()
        text = value
        if label == "current":
            text = truncate_current(value, char_limit=self._current_char_limit)
        resp = await self._http.patch(
            f"/v1/agents/{agent_id}/core-memory/blocks/{label}",
            json={"value": text},
        )
        resp.raise_for_status()

    async def get_block(self, label: str) -> str:
        return await self._get_block(label)

    async def set_block(self, label: str, value: str) -> None:
        await self._set_block(label, value)

    async def save_fact(self, fact: FactIn) -> FactOut:
        agent_id = self._require_agent()
        payload = {
            "text": fact.content,
            "tags": fact.tags,
            "metadata": {"session_id": fact.session_id} if fact.session_id else {},
        }
        # Try modern passages API, then legacy archival-memory.
        for path in (
            f"/v1/agents/{agent_id}/archival-memory",
            f"/v1/agents/{agent_id}/passages",
        ):
            try:
                resp = await self._http.post(path, json=payload)
            except httpx.HTTPError as e:
                logger.warning("archival insert failed path=%s err=%s", path, e)
                continue
            if resp.status_code < 400:
                data = resp.json()
                fact_id = str(
                    data.get("id")
                    or data.get("passage_id")
                    or uuid4()
                )
                return FactOut(
                    id=fact_id,
                    content=fact.content,
                    tags=list(fact.tags),
                    session_id=fact.session_id,
                    created_at=datetime.now(UTC),
                )
        # Fallback: append into human block so M2-1 still works.
        human = await self._get_block("human")
        line = f"- {fact.content}"
        if line not in human:
            human = f"{human.rstrip()}\n{line}".strip()
            await self._set_block("human", human)
        return FactOut(
            id=str(uuid4()),
            content=fact.content,
            tags=list(fact.tags),
            session_id=fact.session_id,
            created_at=datetime.now(UTC),
        )

    async def list_facts(
        self, *, limit: int = 50, query: str | None = None
    ) -> list[FactOut]:
        return await self.search(query or "", top_k=max(1, limit))

    async def update_fact(self, fact_id: str, fact: FactIn) -> FactOut:
        """Insert replacement first, then delete old — avoids data loss on save fail."""
        if not await self._passage_exists(fact_id):
            raise KeyError(fact_id)
        saved = await self.save_fact(fact)
        # Best-effort cleanup of the previous passage (id may rotate on remote).
        await self.delete_fact(fact_id)
        return saved

    async def _passage_exists(self, fact_id: str) -> bool:
        agent_id = self._require_agent()
        for path in (
            f"/v1/agents/{agent_id}/archival-memory/{fact_id}",
            f"/v1/agents/{agent_id}/passages/{fact_id}",
        ):
            try:
                resp = await self._http.get(path)
            except httpx.HTTPError:
                continue
            if resp.status_code < 400:
                return True
            if resp.status_code == 404:
                return False
        # Fallback: scan recent search hits for the id.
        try:
            hits = await self.search("", top_k=50)
        except Exception:  # noqa: BLE001
            return False
        return any(h.id == fact_id for h in hits)

    async def delete_fact(self, fact_id: str) -> bool:
        agent_id = self._require_agent()
        for path in (
            f"/v1/agents/{agent_id}/archival-memory/{fact_id}",
            f"/v1/agents/{agent_id}/passages/{fact_id}",
        ):
            try:
                resp = await self._http.delete(path)
            except httpx.HTTPError:
                continue
            if resp.status_code < 400:
                return True
            if resp.status_code == 404:
                return False
        return False

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]:
        agent_id = self._require_agent()
        params = {"query": query, "top_k": top_k}
        for path in (
            f"/v1/agents/{agent_id}/archival-memory/search",
            f"/v1/agents/{agent_id}/archival-memory",
            f"/v1/agents/{agent_id}/passages/search",
        ):
            try:
                resp = await self._http.get(path, params=params)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400:
                continue
            data = resp.json()
            items = data if isinstance(data, list) else data.get("passages") or data.get("results") or data.get("items") or []
            out: list[FactOut] = []
            for item in items[:top_k]:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("text") or item.get("content") or "")
                if not content:
                    continue
                out.append(
                    FactOut(
                        id=str(item.get("id") or uuid4()),
                        content=content,
                        tags=list(item.get("tags") or []),
                        session_id=(item.get("metadata") or {}).get("session_id")
                        if isinstance(item.get("metadata"), dict)
                        else None,
                    )
                )
            if out:
                return out

        # Fallback: keyword scan of human + current blocks.
        human = await self._get_block("human")
        current = await self._get_block("current")
        blob = f"{human}\n{current}"
        q = (query or "").lower()
        hits: list[FactOut] = []
        for line in blob.splitlines():
            line = line.strip(" -*\t")
            if not line:
                continue
            if not q or any(tok in line.lower() for tok in q.split()):
                hits.append(FactOut(id=str(uuid4()), content=line, tags=["core"]))
            if len(hits) >= top_k:
                break
        return hits

    async def update_user(self, profile: UserProfile) -> UserProfile:
        from fae.memory.profile_block import merge_human_profile

        existing = await self._get_block("human")
        text = merge_human_profile(
            existing,
            display_name=profile.display_name,
            preferences=profile.preferences,
            notes=profile.notes,
        )
        await self._set_block("human", text)
        return profile

    def _require_recall(self) -> RecallStore:
        if self._recall is None:
            raise RuntimeError("RecallStore not configured on LettaMemoryClient")
        return self._recall

    async def append_recall(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self._require_recall().append(session_id, user_text, assistant_text)

    async def list_recall(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[RecallTurn]:
        return self._require_recall().list_hot(session_id, limit=limit)

    async def recall_for_prompt(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
        recent_limit: int = 10,
    ) -> str:
        persona = (await self._get_block("persona")).strip()
        human = (await self._get_block("human")).strip()
        current = clip_current_for_prompt((await self._get_block("current")).strip())
        parts: list[str] = []
        if persona:
            parts.append(f"[persona]\n{persona}")
        if human:
            parts.append(f"[human]\n{human}")
        if current:
            parts.append(f"[current]\n{current}")
        if session_id:
            turns = await self.list_recall(session_id, limit=recent_limit)
            if turns:
                lines = [
                    f"User: {t.user_text}\nAssistant: {t.assistant_text}"
                    for t in turns
                ]
                parts.append("[recent_turns]\n" + "\n---\n".join(lines))
        try:
            facts = await self.search(query, top_k=top_k)
        except Exception:  # noqa: BLE001
            logger.exception("Letta search failed during recall")
            facts = []
        if facts:
            lines = "\n".join(f"- {f.content}" for f in facts)
            parts.append(f"[facts]\n{lines}")
        return "\n\n".join(parts)

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/v1/health")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._http.aclose()
        logger.debug("LettaMemoryClient.close base_url=%s", self.base_url)
