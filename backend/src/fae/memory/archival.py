"""Archival memory backends (Qdrant HTTP or in-process stub)."""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import httpx

from fae.memory.schemas import FactOut

logger = logging.getLogger("fae.memory.archival")

COLLECTION = "fae_archival"
VECTOR_SIZE = 64
DEFAULT_DECAY_DAYS = 180
_DECAY_FACTOR = 0.25


def stub_embed(text: str, *, dim: int = VECTOR_SIZE) -> list[float]:
    """Deterministic pseudo-embedding for offline / tests."""
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    # Expand digest into dim floats in [-1, 1].
    vals: list[float] = []
    seed = digest
    while len(vals) < dim:
        for b in seed:
            vals.append((b / 127.5) - 1.0)
            if len(vals) >= dim:
                break
        seed = hashlib.sha256(seed).digest()
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def decay_multiplier(
    last_accessed: str | None,
    *,
    created_at: str | None = None,
    decay_days: int = DEFAULT_DECAY_DAYS,
    now: datetime | None = None,
) -> float:
    """Return 1.0 if fresh, or _DECAY_FACTOR if stale beyond decay_days."""
    if decay_days <= 0:
        return 1.0
    ref = parse_ts(last_accessed) or parse_ts(created_at)
    if ref is None:
        return 1.0
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current - ref >= timedelta(days=decay_days):
        return _DECAY_FACTOR
    return 1.0


class ArchivalBackend(Protocol):
    mode: str  # ok | stub | down

    async def ensure_ready(self) -> None: ...

    async def upsert(
        self,
        *,
        text: str,
        session_id: str,
        point_id: str | None = None,
    ) -> str: ...

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        session_id: str | None = None,
    ) -> list[FactOut]: ...

    async def health(self) -> str: ...

    async def close(self) -> None: ...


class StubArchival:
    """In-memory archival for tests and when Qdrant is unavailable."""

    mode = "stub"

    def __init__(self, *, decay_days: int = DEFAULT_DECAY_DAYS) -> None:
        # id, text, session_id, vector, created_at, last_accessed
        self._items: list[tuple[str, str, str, list[float], str, str]] = []
        self.decay_days = decay_days

    async def ensure_ready(self) -> None:
        return None

    async def upsert(
        self,
        *,
        text: str,
        session_id: str,
        point_id: str | None = None,
    ) -> str:
        pid = point_id or str(uuid4())
        vec = stub_embed(text)
        sid = (session_id or "").strip() or "default"
        now = _now_iso()
        self._items = [i for i in self._items if i[0] != pid]
        self._items.append((pid, text, sid, vec, now, now))
        return pid

    def set_last_accessed(self, point_id: str, when: str) -> None:
        """Test helper to backdate access for decay checks."""
        updated: list[tuple[str, str, str, list[float], str, str]] = []
        for item in self._items:
            if item[0] == point_id:
                updated.append(
                    (item[0], item[1], item[2], item[3], item[4], when)
                )
            else:
                updated.append(item)
        self._items = updated

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        session_id: str | None = None,
    ) -> list[FactOut]:
        items = self._items
        if session_id is not None:
            sid = (session_id or "").strip() or "default"
            items = [i for i in items if i[2] == sid]
        qv = stub_embed(query)
        scored: list[tuple[float, tuple[str, str, str, list[float], str, str]]] = []
        q = (query or "").lower()
        for item in items:
            score = sum(a * b for a, b in zip(qv, item[3], strict=False))
            if q and q in item[1].lower():
                score += 0.5
            score *= decay_multiplier(
                item[5], created_at=item[4], decay_days=self.decay_days
            )
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        now = _now_iso()
        out: list[FactOut] = []
        for score, (pid, text, sid, _, created, accessed) in scored[:top_k]:
            if score <= 0 and not q:
                continue
            tags = ["archival"]
            if (
                decay_multiplier(
                    accessed, created_at=created, decay_days=self.decay_days
                )
                < 1.0
            ):
                tags.append("decayed")
            out.append(
                FactOut(id=pid, content=text, tags=tags, session_id=sid)
            )
            self.set_last_accessed(pid, now)
        if not out and scored and q:
            for _, (pid, text, sid, _, _, _) in scored[:top_k]:
                out.append(
                    FactOut(id=pid, content=text, tags=["archival"], session_id=sid)
                )
                self.set_last_accessed(pid, now)
        return out

    async def health(self) -> str:
        return "stub"

    async def close(self) -> None:
        return None


class QdrantArchival:
    """Thin Qdrant REST client (no qdrant-client dependency)."""

    mode = "ok"

    def __init__(
        self,
        base_url: str,
        *,
        collection: str = COLLECTION,
        embed_fn=None,
        timeout_s: float = 5.0,
        decay_days: int = DEFAULT_DECAY_DAYS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.collection = collection
        self._embed = embed_fn or stub_embed
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)
        self._ready = False
        self.decay_days = decay_days

    async def ensure_ready(self) -> None:
        if self._ready:
            return
        # Create collection if missing.
        resp = await self._http.get(f"/collections/{self.collection}")
        if resp.status_code == 404:
            create = await self._http.put(
                f"/collections/{self.collection}",
                json={
                    "vectors": {
                        "size": VECTOR_SIZE,
                        "distance": "Cosine",
                    }
                },
            )
            create.raise_for_status()
        elif resp.status_code >= 400:
            resp.raise_for_status()
        self._ready = True

    async def upsert(
        self,
        *,
        text: str,
        session_id: str,
        point_id: str | None = None,
    ) -> str:
        await self.ensure_ready()
        # Qdrant point ids: prefer unsigned int to avoid string-id validation issues.
        pid_uuid = point_id or str(uuid.uuid4())
        try:
            int_id = int(uuid.UUID(pid_uuid).int % (2**63 - 1))
        except ValueError:
            int_id = int(uuid.uuid4().int % (2**63 - 1))
        sid = (session_id or "").strip() or "default"
        now = _now_iso()
        vector = self._embed(text)
        resp = await self._http.put(
            f"/collections/{self.collection}/points",
            params={"wait": "true"},
            json={
                "points": [
                    {
                        "id": int_id,
                        "vector": vector,
                        "payload": {
                            "text": text,
                            "session_id": sid,
                            "kind": "recall_summary",
                            "uuid": pid_uuid,
                            "created_at": now,
                            "last_accessed": now,
                        },
                    }
                ]
            },
        )
        resp.raise_for_status()
        return str(int_id)

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        session_id: str | None = None,
    ) -> list[FactOut]:
        await self.ensure_ready()
        vector = self._embed(query)
        # Over-fetch then re-rank with decay so stale points can drop out.
        fetch_k = max(top_k * 3, top_k)
        body: dict = {
            "vector": vector,
            "limit": fetch_k,
            "with_payload": True,
        }
        if session_id is not None:
            sid = (session_id or "").strip() or "default"
            body["filter"] = {
                "must": [{"key": "session_id", "match": {"value": sid}}]
            }
        resp = await self._http.post(
            f"/collections/{self.collection}/points/search",
            json=body,
        )
        resp.raise_for_status()
        result = resp.json().get("result") or []
        ranked: list[tuple[float, FactOut, str | int]] = []
        for hit in result:
            payload = hit.get("payload") or {}
            text = str(payload.get("text") or "")
            if not text:
                continue
            base_score = float(hit.get("score") or 0.0)
            mult = decay_multiplier(
                payload.get("last_accessed"),
                created_at=payload.get("created_at"),
                decay_days=self.decay_days,
            )
            tags = ["archival"]
            if mult < 1.0:
                tags.append("decayed")
            fact = FactOut(
                id=str(hit.get("id")),
                content=text,
                tags=tags,
                session_id=payload.get("session_id"),
            )
            ranked.append((base_score * mult, fact, hit.get("id")))
        ranked.sort(key=lambda x: x[0], reverse=True)
        out = [f for _, f, _ in ranked[:top_k]]
        now = _now_iso()
        for _, _, point_id in ranked[:top_k]:
            if point_id is None:
                continue
            try:
                await self._http.post(
                    f"/collections/{self.collection}/points/payload",
                    json={
                        "payload": {"last_accessed": now},
                        "points": [point_id],
                    },
                )
            except Exception:  # noqa: BLE001
                logger.debug("failed to touch last_accessed id=%s", point_id)
        return out

    async def health(self) -> str:
        try:
            resp = await self._http.get("/collections")
            if resp.status_code < 400:
                return "ok"
            return "down"
        except httpx.HTTPError:
            return "down"

    async def close(self) -> None:
        await self._http.aclose()


async def create_archival(
    *,
    qdrant_url: str,
    prefer_stub: bool = False,
    decay_days: int = DEFAULT_DECAY_DAYS,
) -> ArchivalBackend:
    if prefer_stub:
        return StubArchival(decay_days=decay_days)
    backend = QdrantArchival(qdrant_url, decay_days=decay_days)
    try:
        status = await backend.health()
        if status != "ok":
            await backend.close()
            logger.warning("Qdrant unhealthy at %s — using stub archival", qdrant_url)
            return StubArchival(decay_days=decay_days)
        await backend.ensure_ready()
        return backend
    except Exception:  # noqa: BLE001
        logger.exception("Qdrant init failed — using stub archival")
        try:
            await backend.close()
        except Exception:  # noqa: BLE001
            pass
        return StubArchival(decay_days=decay_days)
