"""The floor plan: where a restaurant's tables sit, and what else is drawn around them.

One plan per restaurant, one document. It is a *drawing*, and deliberately disposable:
every element carries geometry and a client-generated id, and a table element points at a
row in ``tables`` (:mod:`app.models.table`) rather than containing one. Redrawing the floor
therefore never disturbs an order's ``table_id`` or a printed QR code.

Three kinds of element, which is what the reference sketches actually contain:

``table``
    A table a diner orders from. Always carries ``table_id``; the shape and size are how it
    is drawn, the name and seat count live on the table itself.
``wall``
    A wall, a counter, a pillar - unlabelled furniture that makes the room recognisable.
``text``
    A caption on the plan and nothing else ("Terrace", "Kitchen").

Everything here is tenant-authored data, never instructions (HLD trust boundary), so the
validators are about shape and size only: a closed set of kinds and shapes, finite
coordinates, a bounded element count, and every element inside the canvas.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import IndexModel, ReturnDocument

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.table import MAX_SEATS
from app.models.user import utcnow

ELEMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""Client-generated, stable for the life of the element. A UUID in practice."""

MAX_ELEMENTS = 250
"""A floor with more than 250 drawn things is a different product."""

MAX_TEXT_LENGTH = 80
"""A caption, not a paragraph."""

MIN_CANVAS = 400
MAX_CANVAS = 4000
DEFAULT_CANVAS_WIDTH = 1200
DEFAULT_CANVAS_HEIGHT = 800
"""Canvas units. One unit is one CSS pixel at 100% zoom; the editor scales, the data does not."""

MIN_ELEMENT_SIZE = 16.0
MAX_ELEMENT_SIZE = float(MAX_CANVAS)


class ElementKind(StrEnum):
    """What an element *is*. Only ``TABLE`` can be ordered from."""

    TABLE = "table"
    WALL = "wall"
    TEXT = "text"


class ElementShape(StrEnum):
    """How an element is drawn. Purely visual - nothing downstream reads it."""

    CIRCLE = "circle"
    SQUARE = "square"
    DIAMOND = "diamond"
    RECTANGLE = "rectangle"


class _Element(BaseModel):
    """Geometry and identity shared by a stored element and a submitted one.

    Canvas units, origin at the top left, no zoom baked in: the editor scales the view, the
    document keeps the room.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=64, description="Client-generated; stable for the element's life.")
    kind: ElementKind
    shape: ElementShape = ElementShape.RECTANGLE
    table_id: PyObjectId | None = Field(
        default=None, description="Set on, and only on, a ``table`` element."
    )
    text: str = Field(default="", max_length=MAX_TEXT_LENGTH)
    x: float = Field(ge=0, le=MAX_CANVAS)
    y: float = Field(ge=0, le=MAX_CANVAS)
    width: float = Field(ge=MIN_ELEMENT_SIZE, le=MAX_ELEMENT_SIZE)
    height: float = Field(ge=MIN_ELEMENT_SIZE, le=MAX_ELEMENT_SIZE)
    rotation: float = Field(default=0, ge=-360, le=360)

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, value: object) -> object:
        if isinstance(value, str) and not ELEMENT_ID_PATTERN.match(value):
            raise ValueError("element id must be 1-64 characters of a-z, A-Z, 0-9, '_' or '-'")
        return value

    @field_validator("text", mode="before")
    @classmethod
    def _trim_text(cls, value: object) -> object:
        return re.sub(r"\s+", " ", value.strip()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_text(self) -> Self:
        if self.kind is ElementKind.TEXT and not self.text:
            raise ValueError("a text element needs something to say")
        return self


class FloorPlanElement(_Element):
    """An element as stored: a table element already points at a row in ``tables``."""

    @model_validator(mode="after")
    def _check_table_link(self) -> Self:
        if self.kind is ElementKind.TABLE and self.table_id is None:
            raise ValueError("a table element must point at a table")
        if self.kind is not ElementKind.TABLE and self.table_id is not None:
            raise ValueError("only a table element may point at a table")
        return self


class FloorPlanElementDraft(_Element):
    """An element as submitted by the editor.

    A table element carries the *name* rather than an id, because the editor lets someone
    draw a table and name it before anything exists in the database. ``table_id`` is present
    only for a table that has been saved before; the service resolves the rest.
    """

    label: str = Field(default="", max_length=24, description="Table name, on a table element.")
    seats: int = Field(default=0, ge=0, le=MAX_SEATS)

    @model_validator(mode="after")
    def _check_table_fields(self) -> Self:
        if self.kind is ElementKind.TABLE:
            if not self.label.strip():
                raise ValueError("every table needs a name")
            return self
        if self.table_id is not None or self.label.strip() or self.seats:
            raise ValueError(f"a {self.kind} element cannot carry table details")
        return self


def check_layout(elements: Sequence[_Element], *, width: int, height: int) -> None:
    """Ids are unique, one table is drawn once, and nothing sits outside the canvas.

    The table check is the load-bearing one. Two elements pointing at the same table would
    make one physical table answer to two places on the floor, and the reconciliation that
    produced them has lost a table somewhere - so it is refused at the model boundary
    rather than left to the service to get right every time. Raises ``ValueError``.
    """
    seen: set[str] = set()
    tables: set[PyObjectId] = set()
    for element in elements:
        if element.id in seen:
            raise ValueError(f"two elements share the id '{element.id}'")
        seen.add(element.id)
        if element.table_id is not None:
            if element.table_id in tables:
                raise ValueError("two elements are drawn for the same table")
            tables.add(element.table_id)
        if element.x + element.width > width or element.y + element.height > height:
            raise ValueError(f"element '{element.id}' does not fit on the floor plan")


class FloorPlanDraft(BaseModel):
    """A whole plan as submitted: the editor saves the document, never a single element.

    There is no name on it. One plan per restaurant means it has nothing to be told apart
    from, and the restaurant is already named.

    The Save button in the editor commits a buffer that has been dragged around locally, so
    a partial update would have no meaning - there is no such thing as half a floor.
    """

    model_config = ConfigDict(extra="ignore")

    width: int = Field(default=DEFAULT_CANVAS_WIDTH, ge=MIN_CANVAS, le=MAX_CANVAS)
    height: int = Field(default=DEFAULT_CANVAS_HEIGHT, ge=MIN_CANVAS, le=MAX_CANVAS)
    elements: list[FloorPlanElementDraft] = Field(default_factory=list, max_length=MAX_ELEMENTS)

    @model_validator(mode="after")
    def _check_elements(self) -> Self:
        check_layout(self.elements, width=self.width, height=self.height)
        return self

    def tables(self) -> list[FloorPlanElementDraft]:
        """The table elements, in the order they were drawn."""
        return [e for e in self.elements if e.kind is ElementKind.TABLE]


class FloorPlan(MongoDocument):
    """One restaurant's plan of its floor. At most one document per tenant."""

    tenant_id: PyObjectId
    width: int = Field(default=DEFAULT_CANVAS_WIDTH, ge=MIN_CANVAS, le=MAX_CANVAS)
    height: int = Field(default=DEFAULT_CANVAS_HEIGHT, ge=MIN_CANVAS, le=MAX_CANVAS)
    elements: list[FloorPlanElement] = Field(default_factory=list, max_length=MAX_ELEMENTS)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check_elements(self) -> Self:
        check_layout(self.elements, width=self.width, height=self.height)
        return self

    def table_ids(self) -> list[PyObjectId]:
        """The tables this plan draws, in the order they appear."""
        return [e.table_id for e in self.elements if e.table_id is not None]


class FloorPlanRepository(MongoRepository[FloorPlan]):
    """``floor_plans`` - one document per tenant, unique on ``tenant_id``."""

    collection_name = "floor_plans"
    document_type = FloorPlan

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [IndexModel([("tenant_id", ASCENDING)], name="uq_tenant", unique=True)]
        )

    async def get_for_tenant(self, tenant_id: PyObjectId) -> FloorPlan | None:
        """The tenant's plan, or ``None`` when they have never saved one."""
        return await self.find_one({"tenant_id": tenant_id})

    async def save_for_tenant(self, plan: FloorPlan) -> FloorPlan:
        """Replace the tenant's plan, creating it on the first save.

        An upsert rather than an insert-or-update pair: the unique index makes the two
        racing requests of a double-clicked Save collide otherwise.
        """
        body = plan.to_mongo()
        body.pop("_id", None)
        body.pop("tenant_id", None)
        created_at = body.pop("created_at", utcnow())
        raw = await self.collection.find_one_and_update(
            {"tenant_id": plan.tenant_id},
            {"$set": body, "$setOnInsert": {"tenant_id": plan.tenant_id, "created_at": created_at}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        # ``upsert=True`` with ``ReturnDocument.AFTER`` always has a document to return.
        assert raw is not None
        return FloorPlan.from_mongo(raw)


__all__ = [
    "DEFAULT_CANVAS_HEIGHT",
    "DEFAULT_CANVAS_WIDTH",
    "MAX_CANVAS",
    "MAX_ELEMENTS",
    "MAX_TEXT_LENGTH",
    "MIN_CANVAS",
    "MIN_ELEMENT_SIZE",
    "ElementKind",
    "ElementShape",
    "FloorPlan",
    "FloorPlanDraft",
    "FloorPlanElement",
    "FloorPlanElementDraft",
    "FloorPlanRepository",
]
