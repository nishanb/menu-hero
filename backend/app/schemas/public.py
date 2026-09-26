"""What a diner sees and sends, with no session at all.

Everything here is a projection of a management document, deliberately narrower: a menu
item leaves the short codes, costs, margins and stock dates behind and keeps what a person
at a table needs to choose. Nothing in these bodies identifies the diner - there is nothing
to identify them by, and HLD 8 keeps it that way.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId
from app.models.menu_item import MenuItem
from app.models.order import MAX_NOTE_LENGTH, MAX_QUANTITY, Kot
from app.models.table import Table
from app.models.tenant import Tenant

MAX_ORDER_LINES = 30
"""One round from a phone. A table wanting more can send another."""


class PublicRestaurant(BaseModel):
    name: str
    description: str = ""
    logo: str = ""

    @classmethod
    def from_tenant(cls, tenant: Tenant) -> PublicRestaurant:
        return cls(name=tenant.name, description=tenant.description, logo=tenant.logo)


class PublicTable(BaseModel):
    id: PyObjectId
    label: str

    @classmethod
    def from_table(cls, table: Table) -> PublicTable:
        assert table.id is not None
        return cls(id=table.id, label=table.label)


class PublicVariation(BaseModel):
    name: str
    price: float


class PublicItem(BaseModel):
    id: PyObjectId
    name: str
    description: str = ""
    diet: str = ""
    price: float = 0
    price_from: float = 0
    image_url: str = ""
    variations: list[PublicVariation] = Field(default_factory=list)

    @classmethod
    def from_item(cls, item: MenuItem) -> PublicItem:
        assert item.id is not None
        return cls(
            id=item.id,
            name=item.online_name or item.name,
            description=item.description,
            diet=item.diet,
            price=item.price,
            price_from=item.price_from,
            image_url=item.image_url,
            variations=[PublicVariation(name=v.name, price=v.price) for v in item.variations],
        )


class PublicSection(BaseModel):
    name: str
    items: list[PublicItem] = Field(default_factory=list)


class PublicMenuResponse(BaseModel):
    """Body of ``GET /api/v1/public/restaurants/{tenant_id}/menu``."""

    restaurant: PublicRestaurant
    table: PublicTable | None = Field(
        default=None, description="The table the QR code was on, when the link names one."
    )
    sections: list[PublicSection] = Field(default_factory=list)


class PublicLineIn(BaseModel):
    item_id: PyObjectId
    variation: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)


class PublicOrderIn(BaseModel):
    """Body of ``POST /api/v1/public/restaurants/{tenant_id}/orders``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "table_id": "6650f0c7e6b1a2c3d4e5f6a7",
                    "lines": [{"item_id": "6650f0c7e6b1a2c3d4e5f6b8", "quantity": 2}],
                }
            ]
        }
    )

    table_id: PyObjectId
    lines: list[PublicLineIn] = Field(min_length=1, max_length=MAX_ORDER_LINES)


class PublicOrderOut(BaseModel):
    """What the table is told: the numbers the kitchen and the counter will use."""

    order_number: int
    kot_number: int
    table_label: str

    @classmethod
    def from_kot(cls, kot: Kot) -> PublicOrderOut:
        return cls(
            order_number=kot.order_number, kot_number=kot.number, table_label=kot.table_label
        )
