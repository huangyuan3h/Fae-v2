"""Active-plan HTTP surface.

Used by the FE to recover the active plan when the WebSocket is cold
(e.g. after a page reload before the user sends another chat message),
to drive the user-reengage flow for blocked plan steps, and to let
the user edit / reorder plan steps in place.

Endpoints
  GET    /api/plans/active?session_id=...     return the session's active plan
  POST   /api/plans/{plan_id}/abandon         abandon an active plan
  PATCH  /api/plans/{plan_id}/steps/{step_id} edit title / acceptance in place
  POST   /api/plans/{plan_id}/reorder         move a step to a new index
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from fae.plans import InvalidPlanTransition, PlanStore

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


class StepEditBody(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    acceptance: str | None = Field(default=None, max_length=2000)


@router.patch("/{plan_id}/steps/{step_id}")
async def edit_step(
    plan_id: str,
    step_id: str,
    body: StepEditBody,
    request: Request,
) -> dict[str, Any]:
    """Edit ``title`` / ``acceptance`` of a non-terminal step.

    Returns the refreshed plan so the FE can refresh its local cache
    in one round trip.
    """
    if body.title is None and body.acceptance is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_fields",
                "message": "edit_step: nothing to update (need title or acceptance)",
            },
        )
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
                "message": f"plan {plan_id} is {plan.status}; cannot edit steps",
            },
        )
    if not any(s.id == step_id for s in plan.steps):
        raise HTTPException(
            status_code=404,
            detail={"code": "step_not_in_plan", "message": f"step {step_id} not in plan {plan_id}"},
        )
    try:
        await asyncio.to_thread(
            store.edit_step,
            step_id,
            title=body.title,
            acceptance=body.acceptance,
        )
    except InvalidPlanTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "step_terminal",
                "from": exc.from_status,
                "message": (
                    f"step is {exc.from_status}; cannot edit terminal step"
                ),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(e)})
    refreshed = await asyncio.to_thread(store.get_plan, plan_id)
    assert refreshed is not None
    return {"plan": store.to_dict(refreshed)}


class StepReorderBody(BaseModel):
    step_id: str = Field(min_length=1, max_length=64)
    new_index: int = Field(ge=0, le=10_000)


@router.post("/{plan_id}/reorder")
async def reorder_step(
    plan_id: str,
    body: StepReorderBody,
    request: Request,
) -> dict[str, Any]:
    """Move ``step_id`` to ``new_index`` within the plan.

    Returns the refreshed plan.
    """
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
                "message": f"plan {plan_id} is {plan.status}; cannot reorder steps",
            },
        )
    if not any(s.id == body.step_id for s in plan.steps):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "step_not_in_plan",
                "message": f"step {body.step_id} not in plan {plan_id}",
            },
        )
    try:
        await asyncio.to_thread(
            store.reorder_step, body.step_id, body.new_index
        )
    except InvalidPlanTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "step_terminal",
                "from": exc.from_status,
                "message": (
                    f"step is {exc.from_status}; cannot reorder terminal step"
                ),
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "out_of_range", "message": str(e)},
        )
    refreshed = await asyncio.to_thread(store.get_plan, plan_id)
    assert refreshed is not None
    return {"plan": store.to_dict(refreshed)}