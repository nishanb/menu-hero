"""The diner's side: scan the code on the table, see the menu, order.

    GET   /api/v1/public/restaurants/{tenant_id}/menu?table=...   (anyone)
    POST  /api/v1/public/restaurants/{tenant_id}/orders           (anyone)

No session. A person at table A3 has a phone and a QR code and nothing else, and asking
them to sign in to see what is for dinner is how a restaurant loses the order. What
protects the restaurant instead: only *available* dishes are served here, only tables on
the floor plan can be ordered for, a round is capped, and the ticket says which table sent
it - the same shape a captain's ticket has, so the kitchen and the counter handle both alike.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from app.dependencies.auth import (
    CategoryServiceDep,
    ManagementServiceDep,
    MenuServiceDep,
    OrderServiceDep,
)
from app.dependencies.database import Db
from app.models.base import PyObjectId
from app.models.category import CategoryStatus
from app.models.table import TableRepository
from app.schemas.public import (
    PublicItem,
    PublicMenuResponse,
    PublicOrderIn,
    PublicOrderOut,
    PublicRestaurant,
    PublicSection,
    PublicTable,
)
from app.services.order_service import LineRequest
from app.utils.ids import new_line_id

router = APIRouter(prefix="/public/restaurants")


class ErrorBody(BaseModel):
    detail: str


NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorBody, "description": "No such restaurant, table or dish"}
}
CONFLICT_RESPONSE: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorBody, "description": "The table is being billed, or a dish is off the menu"}
}


@router.get(
    "/{tenant_id}/menu",
    response_model=PublicMenuResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="The menu, as the table sees it",
)
async def public_menu(
    tenant_id: PyObjectId,
    management: ManagementServiceDep,
    categories: CategoryServiceDep,
    menu: MenuServiceDep,
    db: Db,
    table: Annotated[PyObjectId | None, Query(description="The table the QR code was on.")] = None,
) -> PublicMenuResponse:
    """Available dishes only, in the restaurant's section order, plus the table if named.

    A table that is not on the floor plan any more comes back as ``null`` rather than a
    404: the menu is still worth showing, and the page says to ask a server.
    """
    tenant = await management.get_tenant(tenant_id)

    seated = None
    if table is not None:
        found = await TableRepository(db).get(table)
        if found is not None and found.tenant_id == tenant_id and found.is_active:
            seated = PublicTable.from_table(found)

    items = [item for item in await menu.list_items(tenant_id) if item.is_available]
    by_section: dict[str, list[PublicItem]] = {}
    for item in items:
        by_section.setdefault(item.category, []).append(PublicItem.from_item(item))

    # The restaurant's own order first; sections it has not ranked follow in the order
    # the menu happens to hold them. Hidden sections stay hidden.
    ordered = [
        category.name
        for category in await categories.list(tenant_id)
        if category.status is CategoryStatus.ACTIVE
    ]
    hidden = {
        category.name
        for category in await categories.list(tenant_id)
        if category.status is not CategoryStatus.ACTIVE
    }
    names = [name for name in ordered if name in by_section] + [
        name for name in by_section if name not in ordered and name not in hidden
    ]
    return PublicMenuResponse(
        restaurant=PublicRestaurant.from_tenant(tenant),
        table=seated,
        sections=[PublicSection(name=name, items=by_section[name]) for name in names],
    )


@router.post(
    "/{tenant_id}/orders",
    response_model=PublicOrderOut,
    status_code=status.HTTP_201_CREATED,
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
    summary="Order from the table",
)
async def public_order(
    tenant_id: PyObjectId,
    body: PublicOrderIn,
    management: ManagementServiceDep,
    orders: OrderServiceDep,
) -> PublicOrderOut:
    """Straight to the kitchen: the round becomes a ticket the moment it lands."""
    await management.get_tenant(tenant_id)
    kot = await orders.place_from_table(
        tenant_id=tenant_id,
        table_id=body.table_id,
        requests=[
            LineRequest(
                line_id=new_line_id(),
                item_id=line.item_id,
                variation=line.variation,
                quantity=line.quantity,
                note=line.note,
            )
            for line in body.lines
        ],
    )
    return PublicOrderOut.from_kot(kot)
