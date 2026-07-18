"""Archival memory backends (Qdrant HTTP or in-process stub)."""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from typing import Protocol
from uuid import uuid4

import httpx

from fae.memory.schemas import FactOut

logger = logging.getLogger("fae.memory.archival")

COLLECTION = "fae_archival"
VECTOR_SIZE = 64


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

    def __init__(self) -> None:
        self._items: list[tuple[str, str, str, list[float]]] = []
        # (id, text, session_id, vector)

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
        self._items = [i for i in self._items if i[0] != pid]
        self._items.append((pid, text, sid, vec))
        return pid

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
        scored: list[tuple[float, tuple[str, str, str, list[float]]]] = []
        q = (query or "").lower()
        for item in items:
            score = sum(a * b for a, b in zip(qv, item[3], strict=False))
            if q and q in item[1].lower():
                score += 0.5
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[FactOut] = []
        for score, (pid, text, sid, _) in scored[:top_k]:
            if score <= 0 and not q:
                continue
            out.append(
                FactOut(id=pid, content=text, tags=["archival"], session_id=sid)
            )
        if not out and scored and q:
            for _, (pid, text, sid, _) in scored[:top_k]:
                out.append(
                    FactOut(id=pid, content=text, tags=["archival"], session_id=sid)
                )
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.collection = collection
        self._embed = embed_fn or stub_embed
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)
        self._ready = False

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
        body: dict = {
            "vector": vector,
            "limit": top_k,
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
        out: list[FactOut] = []
        for hit in result:
            payload = hit.get("payload") or {}
            text = str(payload.get("text") or "")
            if not text:
                continue
            out.append(
                FactOut(
                    id=str(hit.get("id")),
                    content=text,
                    tags=["archival"],
                    session_id=payload.get("session_id"),
                )
            )
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
) -> ArchivalBackend:
    if prefer_stub:
        return StubArchival()
    backend = QdrantArchival(qdrant_url)
    try:
        status = await backend.health()
        if status != "ok":
            await backend.close()
            logger.warning("Qdrant unhealthy at %s — using stub archival", qdrant_url)
            return StubArchival()
        await backend.ensure_ready()
        return backend
    except Exception:  # noqa: BLE001
        logger.exception("Qdrant init failed — using stub archival")
        try:
            await backend.close()
        except Exception:  # noqa: BLE001
            pass
        return StubArchival()
