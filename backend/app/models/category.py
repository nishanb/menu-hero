"""Menu categories - the sections a menu is read in.

A category is the heading a diner scans before they read a single dish: Starters, Mains,
Desserts. It carries three things and no more:

``name``
    What the section is called. Unique within a restaurant, case-insensitively, because two
    sections called "Starters" is a mistake every time.
``rank``
    Where it sits in the running order. A number rather than a linked list: an owner thinks
    "desserts go last", not "desserts go after cheese".
``status``
    Whether diners see it at all. Hiding a section is a menu decision an owner makes once -
    running out of a dish mid-service is a different thing entirely, and lives on the item.

Deliberately its own collection rather than a list on the tenant. HLD 4 stores an item's
``category_path`` as text on the item, which is right for the immutable published version;
this is the editable side the owner maintains, and it has to be nameable and re-orderable
before any item exists to point at it.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow

NAME_PATTERN = re.compile(r"^[^\x00-\x1f]{1,60}$")
"""1-60 characters, anything a menu heading might legitimately contain except control codes."""

MAX_NAME_LENGTH = 60
MAX_RANK = 999
MAX_CATEGORIES_PER_TENANT = 100
"""A menu with more than a hundred sections is not a menu."""


class CategoryStatus(StrEnum):
    """Whether a section is on the menu a diner reads."""

    ACTIVE = "active"
    HIDDEN = "hidden"


class Category(MongoDocument):
    """One section of one restaurant's menu."""

    tenant_id: PyObjectId
    name: str = Field(max_length=MAX_NAME_LENGTH)
    name_key: str = Field(default="", description="Case-folded ``name``; the uniqueness key.")
    rank: int = Field(
        default=0, ge=0, le=MAX_RANK, description="Running order; lower is read first."
    )
    status: CategoryStatus = CategoryStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        """Collapse whitespace, and refuse anything that would not read as a heading."""
        if not isinstance(value, str):
            return value
        name = re.sub(r"\s+", " ", value.strip())
        if not NAME_PATTERN.match(name):
            raise ValueError("a category name is 1-60 characters and cannot be blank")
        return name

    @model_validator(mode="after")
    def _derive_name_key(self) -> Self:
        """Keep ``name_key`` in step with ``name``; it is what ``uq_tenant_name`` guards."""
        key = self.name.casefold()
        if self.name_key != key:
            object.__setattr__(self, "name_key", key)
        return self


class CategoryRepository(MongoRepository[Category]):
    """``categories`` - unique on (``tenant_id``, ``name_key``)."""

    collection_name = "categories"
    document_type = Category

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("name_key", ASCENDING)],
                    name="uq_tenant_name",
                    unique=True,
                ),
                IndexModel([("tenant_id", ASCENDING), ("rank", ASCENDING)], name="ix_tenant_rank"),
            ]
        )

    async def list_for_tenant(self, tenant_id: PyObjectId) -> list[Category]:
        """A restaurant's sections in reading order.

        Name breaks a tie, so two sections sharing a rank still come back in a stable order
        rather than whichever the storage engine felt like.
        """
        return await self.find(
            {"tenant_id": tenant_id}, sort=[("rank", ASCENDING), ("name_key", ASCENDING)]
        )

    async def next_rank(self, tenant_id: PyObjectId) -> int:
        """One past the last section, so a new one lands at the bottom rather than the top."""
        existing = await self.find({"tenant_id": tenant_id}, limit=1, sort=[("rank", -1)])
        if not existing:
            return 0
        return min(existing[0].rank + 1, MAX_RANK)


__all__ = [
    "MAX_CATEGORIES_PER_TENANT",
    "MAX_NAME_LENGTH",
    "MAX_RANK",
    "Category",
    "CategoryRepository",
    "CategoryStatus",
]
