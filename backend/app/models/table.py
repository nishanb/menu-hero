"""Tables - the physical seats a diner orders from, and their repository.

A table is an *identity*, not a drawing. It is what an order points at
(``orders.table_id`` in HLD 4), what a QR code encodes, and what a table token is minted
for (``POST /tables/{id}/token``), so its ``_id`` has to outlive any number of floor-plan
redraws. Where it sits on the floor, how big it is and what shape it is drawn as all live
on the floor plan (:mod:`app.models.floor_plan`) instead.

The consequence worth stating out loud: removing a table from the floor plan never deletes
this document. It is deactivated, so past orders keep resolving and a printed QR that comes
back next season still points at the same table.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Self

from pydantic import Field, field_validator, model_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,23}$")
"""1-24 characters. ``A1``, ``Table 4``, ``Patio-2`` - what a server would say out loud."""

MAX_SEATS = 40
"""A banquet table, not a hall. Anything larger is two tables."""

MAX_TABLES_PER_TENANT = 200
"""Ceiling on one restaurant's floor. Bounds both the save payload and the collection."""


class Table(MongoDocument):
    """One table at one restaurant."""

    tenant_id: PyObjectId
    label: str = Field(max_length=24, description="What the table is called: A1, Patio 2, ...")
    label_key: str = Field(default="", description="Case-folded ``label``; the uniqueness key.")
    seats: int = Field(default=0, ge=0, le=MAX_SEATS, description="0 when nobody has said.")
    is_active: bool = Field(
        default=True,
        description="False once the table is off the floor plan; the document itself stays.",
    )
    current_token_hash: str | None = Field(
        default=None,
        description="Digest of the table token in play, minted per seating. Never the token.",
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    @field_validator("label", mode="before")
    @classmethod
    def _normalise_label(cls, value: object) -> object:
        """Collapse whitespace and refuse anything that would not read as a table name."""
        if not isinstance(value, str):
            return value
        label = re.sub(r"\s+", " ", value.strip())
        if not LABEL_PATTERN.match(label):
            raise ValueError(
                "a table name is 1-24 characters of letters, digits, space, '.', '/', '_' or '-'"
            )
        return label

    @model_validator(mode="after")
    def _derive_label_key(self) -> Self:
        """Keep ``label_key`` in step with ``label``; it is what ``uq_tenant_label`` guards."""
        key = self.label.casefold()
        if self.label_key != key:
            object.__setattr__(self, "label_key", key)
        return self


class TableRepository(MongoRepository[Table]):
    """``tables`` - unique on (``tenant_id``, ``label_key``)."""

    collection_name = "tables"
    document_type = Table

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("label_key", ASCENDING)],
                    name="uq_tenant_label",
                    unique=True,
                ),
                IndexModel([("tenant_id", ASCENDING), ("is_active", ASCENDING)], name="ix_tenant"),
            ]
        )

    async def list_for_tenant(
        self, tenant_id: PyObjectId, *, active_only: bool = False
    ) -> list[Table]:
        """Every table of one restaurant, oldest first so the order is stable across saves."""
        filter: dict[str, Any] = {"tenant_id": tenant_id}
        if active_only:
            filter["is_active"] = True
        return await self.find(filter, sort=[("created_at", ASCENDING)])

    async def deactivate(self, table_ids: list[PyObjectId]) -> int:
        """Take tables off the floor without deleting them; returns how many changed."""
        if not table_ids:
            return 0
        result = await self.collection.update_many(
            {"_id": {"$in": table_ids}, "is_active": True},
            {"$set": {"is_active": False, "updated_at": utcnow()}},
        )
        return result.modified_count


__all__ = ["LABEL_PATTERN", "MAX_SEATS", "MAX_TABLES_PER_TENANT", "Table", "TableRepository"]
