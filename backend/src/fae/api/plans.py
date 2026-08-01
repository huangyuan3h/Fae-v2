"""Active-plan HTTP surface.

Used by the FE to recover the active plan when the WebSocket is cold
(e.g. after a page reload before the user sends another chat message)
and to drive the user-reengage flow for blocked plan steps.

Endpoints
  GET    /api/plans/active?session_id=...   return the session's active plan
  POST   /api/plans/{plan_id}/abandon       abandon an active plan
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from fae.plans import PlanStore

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _store(request: Request) -> PlanStore:
    store = getattr(request.app.state, "plan_store", None)
    if not isinstance(store, PlanStore):
        raise HTTPException(
            status_code=503,
            detail={"code": "no_plan_store", "message": "plan store unavailable"},
        )
    return store


@router.get("/active")
async def get_active_plan(
    request: Request,
    session_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> dict[str, Any]:
    """Return the active plan for ``session_id`` (``plan=null`` if none)."""
    store = _store(request)
    plan = await asyncio.to_thread(store.get_active_for_session, session_id)
    if plan is None:
        return {"plan": None, "session_id": session_id}
    return {"plan": store.to_dict(plan), "session_id": session_id}


@router.post("/{plan_id}/abandon")
async def abandon_plan(plan_id: str, request: Request) -> dict[str, Any]:
    """Abandon a plan so a new one can take its place."""
    store = _store(request)
    plan = await asyncio.to_thread(store.get_plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"plan {plan_id} not found"},
        )
    if plan.status != "active":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_active",
                "message": f"plan {plan_id} is {plan.status}; cannot abandon",
            },
        )
    await asyncio.to_thread(store.abandon_plan, plan_id)
    return {"plan_id": plan_id, "status": "abandoned"}