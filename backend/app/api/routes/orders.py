"""The POS: seating tables, building orders, sending tickets, printing bills.

    GET    /api/v1/tenants/{tenant_id}/orders                          (member)
    POST   /api/v1/tenants/{tenant_id}/orders                          (member)
    GET    /api/v1/tenants/{tenant_id}/orders/{order_id}               (member)
    POST   /api/v1/tenants/{tenant_id}/orders/{order_id}/lines         (member)
    PATCH  /api/v1/tenants/{tenant_id}/orders/{order_id}/lines/{id}    (member)
    DELETE /api/v1/tenants/{tenant_id}/orders/{order_id}/lines/{id}    (member)
    POST   /api/v1/tenants/{tenant_id}/orders/{order_id}/kot           (member)
    GET    /api/v1/tenants/{tenant_id}/orders/{order_id}/kots          (member)
    POST   /api/v1/tenants/{tenant_id}/orders/{order_id}/bill          (member)
    POST   /api/v1/tenants/{tenant_id}/orders/{order_id}/close         (member)
    POST   /api/v1/tenants/{tenant_id}/orders/{order_id}/cancel        (member)
    GET    /api/v1/tenants/{tenant_id}/kots                            (member)
    GET    /api/v1/tenants/{tenant_id}/kots/{kot_id}                   (member)
    POST   /api/v1/tenants/{tenant_id}/kots/{kot_id}/acknowledge       (member)

Every one of these is open to any member, staff included: the POS is the floor's tool, and
a server who cannot send a ticket is not much use. Owners get nothing extra here on purpose.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.dependencies.auth import CurrentUser, ManagementServiceDep, OrderServiceDep
from app.models import PyObjectId
from app.schemas.order import (
    KotListResponse,
    KotOut,
    LinesAdd,
    LineUpdate,
    OrderListResponse,
    OrderOpen,
    OrderOut,
)
from app.services.order_service import LineRequest

router = APIRouter(prefix="/tenants")

FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    403: {"description": "Not a member of this restaurant"}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"description": "Restaurant, order, line or ticket not found"}
}
STATE_RESPONSE: dict[int | str, dict[str, Any]] = {
    409: {"description": "The order is not in a state that allows this"}
}


@router.get(
    "/{tenant_id}/orders",
    response_model=OrderListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Orders on the floor, or the day's history",
)
async def list_orders(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
    scope: Annotated[
        str, Query(description="'active' for open and billed; 'recent' for everything.")
    ] = "active",
) -> OrderListResponse:
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    found = (
        await orders.list_recent(tenant_id)
        if scope == "recent"
        else await orders.list_active(tenant_id)
    )
    return OrderListResponse(orders=[OrderOut.from_order(order) for order in found])


@router.post(
    "/{tenant_id}/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Seat a table, or start a takeaway bill",
)
async def open_order(
    tenant_id: PyObjectId,
    body: OrderOpen,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    """Seating a table that already has an open order returns that order, not a second."""
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    order = await orders.open(
        tenant_id=tenant_id,
        table_id=body.table_id,
        idempotency_key=body.idempotency_key,
        actor=context,
    )
    return OrderOut.from_order(order)


@router.get(
    "/{tenant_id}/orders/{order_id}",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="One order",
)
async def get_order(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    management.assert_member(context, tenant_id)
    return OrderOut.from_order(await orders.get(tenant_id=tenant_id, order_id=order_id))


@router.post(
    "/{tenant_id}/orders/{order_id}/lines",
    response_model=OrderOut,
    responses={
        400: {"description": "A dish needs a variation chosen, or a field was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        **STATE_RESPONSE,
    },
    summary="Add dishes to an order",
)
async def add_lines(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    body: LinesAdd,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    """Prices are frozen at this moment; the menu changing later does not change the bill."""
    management.assert_member(context, tenant_id)
    order = await orders.add_lines(
        tenant_id=tenant_id,
        order_id=order_id,
        requests=[
            LineRequest(
                line_id=line.id,
                item_id=line.item_id,
                variation=line.variation,
                quantity=line.quantity,
                note=line.note,
            )
            for line in body.lines
        ],
        actor=context,
    )
    return OrderOut.from_order(order)


@router.patch(
    "/{tenant_id}/orders/{order_id}/lines/{line_id}",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Change a line the kitchen has not seen",
)
async def update_line(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    line_id: str,
    body: LineUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    management.assert_member(context, tenant_id)
    order = await orders.update_line(
        tenant_id=tenant_id,
        order_id=order_id,
        line_id=line_id,
        quantity=body.quantity,
        note=body.note,
        actor=context,
    )
    return OrderOut.from_order(order)


@router.delete(
    "/{tenant_id}/orders/{order_id}/lines/{line_id}",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Remove a line the kitchen has not seen",
)
async def remove_line(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    line_id: str,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    management.assert_member(context, tenant_id)
    order = await orders.remove_line(
        tenant_id=tenant_id, order_id=order_id, line_id=line_id, actor=context
    )
    return OrderOut.from_order(order)


@router.post(
    "/{tenant_id}/orders/{order_id}/kot",
    response_model=KotOut,
    status_code=status.HTTP_201_CREATED,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Send the pending lines to the kitchen",
)
async def send_kot(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> KotOut:
    """One ticket for everything not yet sent. Refused when there is nothing pending."""
    management.assert_member(context, tenant_id)
    kot = await orders.send_kot(tenant_id=tenant_id, order_id=order_id, actor=context)
    return KotOut.from_kot(kot)


@router.get(
    "/{tenant_id}/orders/{order_id}/kots",
    response_model=KotListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Every ticket sent for an order",
)
async def list_kots(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> KotListResponse:
    management.assert_member(context, tenant_id)
    kots = await orders.kots_for(tenant_id=tenant_id, order_id=order_id)
    return KotListResponse(kots=[KotOut.from_kot(kot) for kot in kots])


@router.post(
    "/{tenant_id}/orders/{order_id}/bill",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Put the bill on the table",
)
async def bill_order(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    """Refused while lines are pending - the kitchen has to be told before the table is."""
    management.assert_member(context, tenant_id)
    return OrderOut.from_order(
        await orders.bill(tenant_id=tenant_id, order_id=order_id, actor=context)
    )


@router.post(
    "/{tenant_id}/orders/{order_id}/close",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Paid at the counter; the table is free",
)
async def close_order(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    management.assert_member(context, tenant_id)
    return OrderOut.from_order(
        await orders.close(tenant_id=tenant_id, order_id=order_id, actor=context)
    )


@router.post(
    "/{tenant_id}/orders/{order_id}/cancel",
    response_model=OrderOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE, **STATE_RESPONSE},
    summary="Void an order that has not been paid",
)
async def cancel_order(
    tenant_id: PyObjectId,
    order_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> OrderOut:
    management.assert_member(context, tenant_id)
    return OrderOut.from_order(
        await orders.cancel(tenant_id=tenant_id, order_id=order_id, actor=context)
    )


@router.get(
    "/{tenant_id}/kots",
    response_model=KotListResponse,
    responses=FORBIDDEN_RESPONSE,
    summary="The kitchen's queue: unacknowledged tickets of orders still on the floor",
)
async def list_active_kots(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> KotListResponse:
    management.assert_member(context, tenant_id)
    kots = await orders.active_kots(tenant_id)
    return KotListResponse(kots=[KotOut.from_kot(kot) for kot in kots])


@router.post(
    "/{tenant_id}/kots/{kot_id}/acknowledge",
    response_model=KotOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="The kitchen has seen this ticket",
)
async def acknowledge_kot(
    tenant_id: PyObjectId,
    kot_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> KotOut:
    management.assert_member(context, tenant_id)
    kot = await orders.acknowledge_kot(tenant_id=tenant_id, kot_id=kot_id, actor=context)
    return KotOut.from_kot(kot)


@router.get(
    "/{tenant_id}/kots/{kot_id}",
    response_model=KotOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="One kitchen ticket",
)
async def get_kot(
    tenant_id: PyObjectId,
    kot_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> KotOut:
    management.assert_member(context, tenant_id)
    return KotOut.from_kot(await orders.get_kot(tenant_id=tenant_id, kot_id=kot_id))
