"""The floor plan of a restaurant, and the tables on it.

    GET /api/v1/tenants/{tenant_id}/floor-plan   (member)
    PUT /api/v1/tenants/{tenant_id}/floor-plan   (owner or admin)

Read is open to any member because a server needs to know which table is which; writing the
floor is an owner's job, like the rest of the restaurant's setup.

There is one plan per restaurant and the whole of it is written at once: the editor is a
buffer with Save and Discard, so a partial update would describe half a room.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.dependencies.auth import CurrentUser, FloorPlanServiceDep, ManagementServiceDep
from app.models import PyObjectId
from app.schemas.floor_plan import FloorPlanResponse, FloorPlanSave

router = APIRouter(prefix="/tenants")

FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    403: {"description": "Not a member of this restaurant"}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {404: {"description": "Restaurant not found"}}


@router.get(
    "/{tenant_id}/floor-plan",
    response_model=FloorPlanResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="The floor plan and its tables",
)
async def get_floor_plan(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    floor_plans: FloorPlanServiceDep,
) -> FloorPlanResponse:
    """An empty canvas when nothing has been drawn yet, never a 404."""
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    plan, tables = await floor_plans.get(tenant_id)
    return FloorPlanResponse.from_plan(plan, tables)


@router.put(
    "/{tenant_id}/floor-plan",
    response_model=FloorPlanResponse,
    responses={
        400: {"description": "An element or a table name was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        409: {"description": "Two tables ended up with the same name"},
    },
    summary="Save the floor plan (owner or admin)",
)
async def save_floor_plan(
    tenant_id: PyObjectId,
    body: FloorPlanSave,
    context: CurrentUser,
    management: ManagementServiceDep,
    floor_plans: FloorPlanServiceDep,
) -> FloorPlanResponse:
    """Replace the plan and reconcile the tables it draws.

    Taking a table off the plan does not delete it: it is deactivated, so its past orders
    still resolve and a QR code already printed for it works again the moment it is put
    back.
    """
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    plan, tables = await floor_plans.save(tenant_id=tenant_id, draft=body, actor=context)
    return FloorPlanResponse.from_plan(plan, tables)
