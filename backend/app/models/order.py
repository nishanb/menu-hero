"""Orders and kitchen tickets - what the POS writes.

An order is one visit's worth of food: it opens when a table is seated (or a takeaway bill
is started), gathers lines as the table orders, and closes when the bill is paid at the
counter. HLD 3.3 sets the two rules everything here follows:

* **one writer** - every change goes through :class:`~app.services.order_service.OrderService`,
  never straight to the collection, so the invariants below hold whoever the caller is;
* **checkout stops at the KOT** - there is no payment here, only a bill printed and a table
  freed once the counter has taken the money.

Three facts about the shape, each of which is a bug if forgotten:

``lines`` **snapshot the menu.** A line carries the dish's name and price *as ordered*. The
menu is edited all day; a bill has to say what the table was charged, not what the item costs
now, and a KOT has to name the dish the kitchen was told to make.

**A line is either pending or sent.** ``kot_id`` is empty until the line goes to the kitchen
and never changes after. Quantity and notes are editable only while pending - once a ticket
is on the pass, changing the record without changing the ticket is how kitchens get lied to.

**One open order per table.** Enforced by a partial unique index, not just by the service:
two servers tapping the same table at once must not seat it twice.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import DESCENDING, IndexModel, ReturnDocument

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow

MAX_LINES = 200
MAX_QUANTITY = 99
MAX_NOTE_LENGTH = 120
MAX_NAME_LENGTH = 200

LINE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OrderKind(StrEnum):
    """Where the food is going."""

    DINE_IN = "dine-in"
    TAKEAWAY = "takeaway"


class OrderStatus(StrEnum):
    """The life of an order, in the order it happens.

    ``open`` while the table is still ordering; ``billed`` once the bill is on the table and
    nothing more may be added; ``closed`` when the counter has been paid; ``cancelled`` if
    it never got that far. HLD 3.3's diner-facing ``placed → in_kitchen → served`` lives on
    the lines (``kot_id``) rather than the order, because a table sends several tickets.
    """

    OPEN = "open"
    BILLED = "billed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class LineVariation(BaseModel):
    """The form of the dish chosen, snapshotted with its price."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=MAX_NAME_LENGTH)
    price: float = Field(ge=0)


class OrderLine(BaseModel):
    """One dish on the ticket, at the price it was ordered at."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=64, description="Client-generated; stable for the line's life.")
    item_id: PyObjectId
    name: str = Field(max_length=MAX_NAME_LENGTH)
    variation: LineVariation | None = None
    quantity: int = Field(ge=1, le=MAX_QUANTITY)
    unit_price: float = Field(ge=0, description="Per unit, after the variation is chosen.")
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH, description="For the kitchen.")
    kot_id: PyObjectId | None = Field(
        default=None, description="Set once the line has gone to the kitchen; never cleared."
    )
    added_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, value: object) -> object:
        if isinstance(value, str) and not LINE_ID_PATTERN.match(value):
            raise ValueError("line id must be 1-64 characters of a-z, A-Z, 0-9, '_' or '-'")
        return value

    @field_validator("note", mode="before")
    @classmethod
    def _trim_note(cls, value: object) -> object:
        return re.sub(r"\s+", " ", value.strip()) if isinstance(value, str) else value

    @property
    def sent(self) -> bool:
        """True once the kitchen has this line on a ticket."""
        return self.kot_id is not None

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class Order(MongoDocument):
    """One visit's worth of food."""

    tenant_id: PyObjectId
    number: int = Field(ge=1, description="Per-restaurant, sequential. What people say aloud.")
    kind: OrderKind = OrderKind.DINE_IN
    table_id: PyObjectId | None = None
    table_label: str = Field(default="", max_length=24, description="Snapshot, for tickets.")
    status: OrderStatus = OrderStatus.OPEN
    lines: list[OrderLine] = Field(default_factory=list, max_length=MAX_LINES)
    kot_ids: list[PyObjectId] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=128)
    opened_by: PyObjectId | None = Field(
        default=None, description="The captain who opened it; None when the table did, by QR."
    )
    opened_at: datetime = Field(default_factory=utcnow)
    billed_at: datetime | None = None
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.kind is OrderKind.DINE_IN and self.table_id is None:
            raise ValueError("a dine-in order needs a table")
        if self.kind is OrderKind.TAKEAWAY and self.table_id is not None:
            raise ValueError("a takeaway order has no table")
        seen: set[str] = set()
        for line in self.lines:
            if line.id in seen:
                raise ValueError(f"two lines share the id '{line.id}'")
            seen.add(line.id)
        return self

    @property
    def subtotal(self) -> float:
        return round(sum(line.total for line in self.lines), 2)

    @property
    def pending_lines(self) -> list[OrderLine]:
        """What the kitchen has not been told about yet."""
        return [line for line in self.lines if not line.sent]

    @property
    def is_open(self) -> bool:
        return self.status is OrderStatus.OPEN


class KotLine(BaseModel):
    """What the kitchen reads: dish, how many, which form, and anything the table said."""

    model_config = ConfigDict(extra="ignore")

    line_id: str
    name: str
    variation: str = ""
    quantity: int
    note: str = ""


class KotSource(StrEnum):
    """Where a ticket came from. The kitchen treats them the same; the board says which."""

    POS = "pos"
    """A captain at the till."""
    DINER = "diner"
    """The table itself, through the QR menu. Reserved: the diner flow is not live yet."""


class Kot(MongoDocument):
    """A kitchen order ticket: the lines sent to the pass in one go.

    ``acknowledged_at`` is the kitchen saying "seen" - the one thing the board asks of it.
    Set once, by whoever tapped, and never cleared.
    """

    tenant_id: PyObjectId
    order_id: PyObjectId
    number: int = Field(ge=1, description="Per-restaurant, sequential. The kitchen calls it.")
    order_number: int
    kind: OrderKind
    table_label: str = ""
    lines: list[KotLine] = Field(default_factory=list)
    source: KotSource = KotSource.POS
    sent_by: PyObjectId | None = Field(
        default=None, description="The captain who sent it; None when the table did, by QR."
    )
    sent_by_name: str = Field(
        default="", description="Snapshot: who sent it, as the board says it."
    )
    sent_at: datetime = Field(default_factory=utcnow)
    acknowledged_at: datetime | None = None
    acknowledged_by: PyObjectId | None = None


class OrderRepository(MongoRepository[Order]):
    """``orders`` - one open order per table, one order per idempotency key."""

    collection_name = "orders"
    document_type = Order

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("table_id", ASCENDING)],
                    name="uq_open_table",
                    unique=True,
                    partialFilterExpression={
                        "status": OrderStatus.OPEN.value,
                        "table_id": {"$type": "objectId"},
                    },
                ),
                IndexModel(
                    [("tenant_id", ASCENDING), ("idempotency_key", ASCENDING)],
                    name="uq_idempotency",
                    unique=True,
                    partialFilterExpression={"idempotency_key": {"$type": "string"}},
                ),
                IndexModel(
                    [("tenant_id", ASCENDING), ("status", ASCENDING), ("opened_at", DESCENDING)],
                    name="ix_tenant_status",
                ),
                IndexModel(
                    [("tenant_id", ASCENDING), ("number", ASCENDING)],
                    name="uq_tenant_number",
                    unique=True,
                ),
            ]
        )

    async def list_for_tenant(
        self, tenant_id: PyObjectId, *, statuses: list[OrderStatus] | None = None, limit: int = 200
    ) -> list[Order]:
        """Orders, newest first. ``statuses`` narrows to the ones a screen cares about."""
        criteria: dict[str, Any] = {"tenant_id": tenant_id}
        if statuses:
            criteria["status"] = {"$in": [status.value for status in statuses]}
        return await self.find(criteria, limit=limit, sort=[("opened_at", DESCENDING)])

    async def open_for_table(self, tenant_id: PyObjectId, table_id: PyObjectId) -> Order | None:
        """The order this table is currently running up, if any."""
        return await self.find_one(
            {"tenant_id": tenant_id, "table_id": table_id, "status": OrderStatus.OPEN.value}
        )

    async def replace(self, order: Order) -> Order:
        """Write the whole document back and return it as stored.

        Whole-document replacement rather than field patches, because every mutation the
        service makes touches ``lines`` and the totals derived from them; a partial write
        that got the lines right and the status wrong would be worse than a rewrite.
        """
        assert order.id is not None
        order.updated_at = utcnow()
        body = order.to_mongo()
        body.pop("_id", None)
        raw = await self.collection.find_one_and_replace(
            {"_id": order.id}, body, return_document=ReturnDocument.AFTER
        )
        assert raw is not None
        return Order.from_mongo(raw)


class KotRepository(MongoRepository[Kot]):
    """``kots`` - the tickets, in the order they went to the kitchen."""

    collection_name = "kots"
    document_type = Kot

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("number", ASCENDING)],
                    name="uq_tenant_number",
                    unique=True,
                ),
                IndexModel([("order_id", ASCENDING)], name="ix_order"),
            ]
        )

    async def list_for_order(self, order_id: PyObjectId) -> list[Kot]:
        return await self.find({"order_id": order_id}, sort=[("number", ASCENDING)])

    async def list_unacknowledged(self, order_ids: Sequence[PyObjectId]) -> list[Kot]:
        """The tickets of the given orders the kitchen has not yet seen, oldest first.

        A queue, not a log: the one the kitchen is latest on sits on top, and a ticket that
        has been acknowledged is not in it. The order's own ``kots`` endpoint is the log.
        """
        if not order_ids:
            return []
        return await self.find(
            {"order_id": {"$in": list(order_ids)}, "acknowledged_at": None},
            sort=[("number", ASCENDING)],
        )


class SequenceRepository:
    """Per-restaurant counters, for order and ticket numbers people say out loud.

    ``find_one_and_update`` with ``$inc`` is atomic on a single document, which is what makes
    two servers opening orders at the same moment get 41 and 42 rather than 41 and 41.
    """

    collection_name = "sequences"

    def __init__(self, database: Any) -> None:
        self._collection = database[self.collection_name]

    async def next(self, tenant_id: ObjectId, name: str) -> int:
        raw = await self._collection.find_one_and_update(
            {"tenant_id": tenant_id, "name": name},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        value: int = raw["value"]
        return value


__all__ = [
    "MAX_LINES",
    "MAX_NOTE_LENGTH",
    "MAX_QUANTITY",
    "Kot",
    "KotLine",
    "KotRepository",
    "LineVariation",
    "Order",
    "OrderKind",
    "OrderLine",
    "OrderRepository",
    "OrderStatus",
    "SequenceRepository",
]
