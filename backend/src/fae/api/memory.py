"""Memory browser + consolidation HTTP API (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fae.memory.consolidation import MemoryConsolidator, SleeptimeScheduler
from fae.memory.core_budget import core_stats_from_client
from fae.memory.factory import MemoryStack
from fae.memory.profile_block import CITY_KEY, TIMEZONE_KEY, parse_human_profile
from fae.memory.schemas import FactIn, UserProfile
from fae.pipecat.services.letta_memory import LettaMemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    city: str | None = None
    timezone: str | None = None
    notes: str | None = None


class ProfileOut(BaseModel):
    display_name: str | None = None
    city: str | None = None
    timezone: str | None = None
    preferences: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None
    human: str = ""


@router.get("/profile", response_model=ProfileOut)
async def memory_get_profile(request: Request) -> ProfileOut:
    """Read Name / City / Timezone from the core human block."""
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    human = await memory.client.get_block("human")
    parsed = parse_human_profile(human)
    notes = "\n".join(parsed.notes).strip() or None
    return ProfileOut(
        display_name=parsed.display_name,
        city=parsed.city,
        timezone=parsed.timezone,
        preferences=parsed.preferences,
        notes=notes,
        human=human,
    )


@router.put("/profile", response_model=ProfileOut)
async def memory_put_profile(body: ProfileUpdate, request: Request) -> ProfileOut:
    """Upsert display name, city, and timezone into the human block."""
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    prefs: dict[str, str] = {}
    if body.city is not None:
        city = body.city.strip()
        if city:
            prefs[CITY_KEY] = city
    if body.timezone is not None:
        tz = body.timezone.strip()
        if tz:
            prefs[TIMEZONE_KEY] = tz
    name = body.display_name.strip() if body.display_name else None
    notes = body.notes.strip() if body.notes else None
    if not name and not prefs and notes is None:
        raise HTTPException(status_code=400, detail="no profile fields provided")
    await memory.client.update_user(
        UserProfile(display_name=name or None, preferences=prefs, notes=notes)
    )
    if city := prefs.get(CITY_KEY):
        await memory.client.save_fact(
            FactIn(content=f"User lives in {city}", tags=["identity", "location", "city"])
        )
    return await memory_get_profile(request)


@router.get("/stats")
async def memory_stats(request: Request) -> dict:
    """Core block sizes, hot recall count, and archival health."""
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    client = memory.client if memory else None
    recall = getattr(request.app.state, "recall_store", None)
    archival = getattr(request.app.state, "archival", None)
    core = await core_stats_from_client(client)
    archival_status = "off"
    if archival is not None:
        try:
            archival_status = await archival.health()
        except Exception:  # noqa: BLE001
            archival_status = "down"
    episodic = getattr(request.app.state, "episodic", None)
    return {
        "recall_turns": recall.total_hot() if recall is not None else 0,
        "core": core,
        "archival": archival_status,
        "events": episodic.count() if episodic is not None else 0,
        "sleeptime": (
            "on"
            if getattr(request.app.state, "sleeptime", None) is not None
            else "off"
        ),
    }


@router.get("/events")
async def memory_events(
    request: Request,
    session_id: str | None = None,
    limit: int = 50,
    q: str | None = None,
) -> dict:
    """List episodic life events (optional session / text filter)."""
    episodic = getattr(request.app.state, "episodic", None)
    if episodic is None:
        raise HTTPException(status_code=503, detail="episodic memory unavailable")
    events = episodic.list_events(session_id=session_id, limit=limit, query=q)
    return {
        "events": [
            {
                "id": e.id,
                "session_id": e.session_id,
                "kind": e.kind,
                "summary": e.summary,
                "raw_text": e.raw_text,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "links": [
                    {
                        "event_id": lk.event_id,
                        "target_kind": lk.target_kind,
                        "target_id": lk.target_id,
                    }
                    for lk in e.links
                ],
            }
            for e in events
        ]
    }


@router.get("/facts")
async def memory_list_facts(
    request: Request,
    limit: int = 50,
    q: str | None = None,
) -> dict:
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    facts = await memory.client.list_facts(limit=limit, query=q)
    return {
        "facts": [
            {
                "id": f.id,
                "content": f.content,
                "tags": f.tags,
                "session_id": f.session_id,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ]
    }


@router.post("/facts")
async def memory_create_fact(body: FactIn, request: Request) -> dict:
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    fact = await memory.client.save_fact(body)
    return {
        "id": fact.id,
        "content": fact.content,
        "tags": fact.tags,
        "session_id": fact.session_id,
        "created_at": fact.created_at.isoformat() if fact.created_at else None,
    }


@router.patch("/facts/{fact_id}")
async def memory_update_fact(fact_id: str, body: FactIn, request: Request) -> dict:
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    try:
        fact = await memory.client.update_fact(fact_id, body)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="fact not found") from e
    return {
        "id": fact.id,
        "content": fact.content,
        "tags": fact.tags,
        "session_id": fact.session_id,
        "created_at": fact.created_at.isoformat() if fact.created_at else None,
    }


@router.delete("/facts/{fact_id}")
async def memory_delete_fact(fact_id: str, request: Request) -> dict:
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    ok = await memory.client.delete_fact(fact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="fact not found")
    return {"ok": True, "id": fact_id}


@router.get("/search")
async def memory_search(
    request: Request,
    q: str,
    top_k: int = 10,
    session_id: str | None = None,
) -> dict:
    """Unified search across facts, archival, and episodic events."""
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")
    facts = await memory.client.search(query, top_k=top_k)
    sid_filter = (session_id or "").strip() or None
    if sid_filter:
        facts = [f for f in facts if not f.session_id or f.session_id == sid_filter]
    archival_hits = []
    if memory.archival is not None:
        archival_hits = await memory.archival.search(
            query, top_k=top_k, session_id=session_id
        )
    events = []
    episodic = getattr(request.app.state, "episodic", None)
    if episodic is not None:
        events = episodic.list_events(session_id=session_id, limit=top_k, query=query)
    return {
        "query": query,
        "facts": [
            {
                "id": f.id,
                "content": f.content,
                "tags": f.tags,
                "source": "fact",
            }
            for f in facts
        ],
        "archival": [
            {
                "id": f.id,
                "content": f.content,
                "tags": f.tags,
                "source": "archival",
            }
            for f in archival_hits
        ],
        "events": [
            {
                "id": e.id,
                "content": e.summary,
                "kind": e.kind,
                "source": "event",
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.get("/timeline")
async def memory_timeline(
    request: Request,
    limit: int = 40,
    session_id: str | None = None,
) -> dict:
    """Merged timeline points for the memory browser chart."""
    memory: LettaMemoryService | None = getattr(request.app.state, "memory", None)
    if memory is None or memory.client is None:
        raise HTTPException(status_code=503, detail="memory unavailable")
    points: list[dict] = []
    facts = await memory.client.list_facts(limit=limit)
    sid_filter = (session_id or "").strip() or None
    for f in facts:
        if sid_filter and f.session_id and f.session_id != sid_filter:
            continue
        points.append(
            {
                "id": f.id,
                "kind": "fact",
                "label": f.content[:80],
                "at": f.created_at.isoformat() if f.created_at else None,
                "tags": f.tags,
            }
        )
    episodic = getattr(request.app.state, "episodic", None)
    if episodic is not None:
        for e in episodic.list_events(session_id=session_id, limit=limit):
            points.append(
                {
                    "id": e.id,
                    "kind": "event",
                    "label": e.summary[:80],
                    "at": e.created_at.isoformat() if e.created_at else None,
                    "tags": [e.kind],
                }
            )
    points.sort(key=lambda p: p.get("at") or "", reverse=True)
    return {"points": points[:limit]}


@router.post("/consolidate")
async def memory_consolidate(
    request: Request,
    session_id: str = "default",
) -> dict:
    """Trigger sleeptime consolidation for a session (smoke / ops)."""
    scheduler = getattr(request.app.state, "sleeptime", None)
    if not isinstance(scheduler, SleeptimeScheduler):
        # Allow on-demand consolidate even if background scheduler is off.
        stack: MemoryStack = getattr(request.app.state, "memory_stack", MemoryStack())
        if stack.client is None or stack.recall is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        consolidator = MemoryConsolidator(
            stack.client,
            stack.recall,
            archival=stack.archival,
            compactor=stack.compactor,
            current_char_limit=request.app.state.settings.core_current_char_limit,
            max_runtime_s=request.app.state.settings.sleeptime_max_runtime_s,
        )
        result = await consolidator.consolidate(session_id)
    else:
        result = await scheduler.consolidate_now(session_id)
    return {
        "session_id": result.session_id,
        "summarized_turns": result.summarized_turns,
        "facts_saved": result.facts_saved,
        "current_updated": result.current_updated,
        "compacted": result.compacted,
        "skipped": result.skipped,
        "elapsed_s": round(result.elapsed_s, 3),
    }
