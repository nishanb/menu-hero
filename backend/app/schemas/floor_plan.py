"""HTTP schemas of the floor-plan endpoints.

The request body is the whole plan (:class:`~app.models.floor_plan.FloorPlanDraft`): the
editor holds the floor in a local buffer while it is being dragged around and commits it on
Save, so there is no meaningful partial update.

The response is deliberately the plan *and* its tables together. The plan says where a
table is drawn; the table says what it is called and how many it seats, and it is the half
that a QR code and an order point at. One round trip, because the editor needs both to draw
anything at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId
from app.models.floor_plan import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    MAX_CANVAS,
    MAX_ELEMENTS,
    MIN_CANVAS,
    ElementKind,
    ElementShape,
    FloorPlan,
    FloorPlanDraft,
)
from app.models.table import Table

FLOOR_PLAN_EXAMPLE: dict[str, Any] = {
    "width": DEFAULT_CANVAS_WIDTH,
    "height": DEFAULT_CANVAS_HEIGHT,
    "elements": [
        {
            "id": "5f0f2b1a-6b1e-4f0a-9a1f-2c3d4e5f6a7b",
            "kind": "table",
            "shape": "circle",
            "label": "A1",
            "seats": 4,
            "x": 120,
            "y": 80,
            "width": 96,
            "height": 96,
        },
        {
            "id": "7b6a5f4e-3d2c-4b1a-8e9f-0a1b2c3d4e5f",
            "kind": "text",
            "text": "Terrace",
            "x": 120,
            "y": 32,
            "width": 160,
            "height": 32,
        },
    ],
}


class FloorPlanSave(FloorPlanDraft):
    """Body of ``PUT /api/v1/tenants/{tenant_id}/floor-plan``.

    A table element carries ``label`` and ``seats`` rather than an id when it is new: the
    editor can draw and name a table before anything exists in the database, and the server
    is what decides whether that is a fresh table or one coming back onto the floor.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [FLOOR_PLAN_EXAMPLE]})


class TableOut(BaseModel):
    """One table, as identity: what a QR code will be printed for."""

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId
    label: str
    seats: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_table(cls, table: Table) -> TableOut:
        """Project a stored :class:`~app.models.table.Table`."""
        return cls.model_validate(table, from_attributes=True)


class FloorPlanElementOut(BaseModel):
    """One drawn element. ``table_id`` is the join back to :class:`TableOut`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: ElementKind
    shape: ElementShape
    table_id: PyObjectId | None = None
    text: str = ""
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0


class FloorPlanResponse(BaseModel):
    """Body of both floor-plan endpoints.

    A restaurant that has never opened the editor gets an empty plan rather than a 404 -
    "no plan yet" is the ordinary first state, and the editor needs a canvas either way.
    """

    width: int = Field(ge=MIN_CANVAS, le=MAX_CANVAS)
    height: int = Field(ge=MIN_CANVAS, le=MAX_CANVAS)
    elements: list[FloorPlanElementOut] = Field(default_factory=list, max_length=MAX_ELEMENTS)
    tables: list[TableOut] = Field(
        default_factory=list, description="Active tables of this restaurant."
    )
    updated_at: datetime | None = None

    @classmethod
    def from_plan(cls, plan: FloorPlan, tables: list[Table]) -> FloorPlanResponse:
        """Pair a stored plan with the tables it draws."""
        return cls(
            width=plan.width,
            height=plan.height,
            elements=[
                FloorPlanElementOut.model_validate(e, from_attributes=True) for e in plan.elements
            ],
            tables=[TableOut.from_table(table) for table in tables],
            updated_at=plan.updated_at,
        )


__all__ = [
    "FloorPlanElementOut",
    "FloorPlanResponse",
    "FloorPlanSave",
    "TableOut",
]
