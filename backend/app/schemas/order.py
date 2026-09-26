"""HTTP schemas of the POS endpoints: orders, their lines, and kitchen tickets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId
from app.models.order import (
    MAX_NOTE_LENGTH,
    MAX_QUANTITY,
    Kot,
    KotSource,
    Order,
    OrderKind,
    OrderStatus,
)


class OrderOpen(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/orders``.

    A ``table_id`` seats a table; leaving it out starts a takeaway bill. The idempotency key
    is the takeaway's guard against a double tap, since it has no table index to lean on.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"table_id": "665f1a2b3c4d5e6f7a8b9c0d"}]}
    )

    table_id: PyObjectId | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class LineIn(BaseModel):
    """One dish to add. ``variation`` names the form when the dish comes in several."""

    id: str = Field(min_length=1, max_length=64, description="Client-generated line id.")
    item_id: PyObjectId
    variation: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)


class LinesAdd(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/orders/{order_id}/lines``."""

    lines: list[LineIn] = Field(min_length=1, max_length=50)


class LineUpdate(BaseModel):
    """Body of ``PATCH .../lines/{line_id}``. Only what is present changes."""

    quantity: int | None = Field(default=None, ge=1, le=MAX_QUANTITY)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class LineVariationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    price: float


class LineOut(BaseModel):
    """One line as stored, with the price it was ordered at."""

    id: str
    item_id: PyObjectId
    name: str
    variation: LineVariationOut | None = None
    quantity: int
    unit_price: float
    total: float
    note: str = ""
    kot_id: PyObjectId | None = None
    added_at: datetime


class OrderOut(BaseModel):
    """One order, with its totals worked out here so no client adds them up differently."""

    id: PyObjectId
    number: int
    kind: OrderKind
    status: OrderStatus
    table_id: PyObjectId | None = None
    table_label: str = ""
    lines: list[LineOut] = Field(default_factory=list)
    kot_ids: list[PyObjectId] = Field(default_factory=list)
    pending_count: int = Field(description="Lines the kitchen has not been told about.")
    subtotal: float
    total: float
    opened_at: datetime
    billed_at: datetime | None = None
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None

    @classmethod
    def from_order(cls, order: Order) -> OrderOut:
        return cls(
            id=_require(order.id),
            number=order.number,
            kind=order.kind,
            status=order.status,
            table_id=order.table_id,
            table_label=order.table_label,
            lines=[
                LineOut(
                    id=line.id,
                    item_id=line.item_id,
                    name=line.name,
                    variation=(
                        LineVariationOut.model_validate(line.variation, from_attributes=True)
                        if line.variation
                        else None
                    ),
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    total=line.total,
                    note=line.note,
                    kot_id=line.kot_id,
                    added_at=line.added_at,
                )
                for line in order.lines
            ],
            kot_ids=list(order.kot_ids),
            pending_count=len(order.pending_lines),
            subtotal=order.subtotal,
            # No tax line yet: the restaurant has nowhere to say its GST rate, and inventing
            # one on a bill would be worse than leaving it off. Total equals subtotal until
            # that setting exists.
            total=order.subtotal,
            opened_at=order.opened_at,
            billed_at=order.billed_at,
            closed_at=order.closed_at,
            cancelled_at=order.cancelled_at,
        )


class OrderListResponse(BaseModel):
    orders: list[OrderOut] = Field(default_factory=list)


class KotLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_id: str
    name: str
    variation: str = ""
    quantity: int
    note: str = ""


class KotOut(BaseModel):
    """A kitchen ticket, exactly as the kitchen should read it."""

    id: PyObjectId
    number: int
    order_id: PyObjectId
    order_number: int
    kind: OrderKind
    table_label: str = ""
    lines: list[KotLineOut] = Field(default_factory=list)
    source: KotSource
    sent_by_name: str = ""
    sent_at: datetime
    acknowledged_at: datetime | None = None

    @classmethod
    def from_kot(cls, kot: Kot) -> KotOut:
        return cls(
            id=_require(kot.id),
            number=kot.number,
            order_id=kot.order_id,
            order_number=kot.order_number,
            kind=kot.kind,
            table_label=kot.table_label,
            lines=[KotLineOut.model_validate(line, from_attributes=True) for line in kot.lines],
            source=kot.source,
            sent_by_name=kot.sent_by_name,
            sent_at=kot.sent_at,
            acknowledged_at=kot.acknowledged_at,
        )


class KotListResponse(BaseModel):
    kots: list[KotOut] = Field(default_factory=list)


def _require(value: Any) -> PyObjectId:
    assert value is not None, "a stored document always has an id"
    result: PyObjectId = value
    return result


__all__ = [
    "KotListResponse",
    "KotOut",
    "LineIn",
    "LineUpdate",
    "LinesAdd",
    "OrderListResponse",
    "OrderOpen",
    "OrderOut",
]
