"""HTTP schemas of the menu-category endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId
from app.models.category import MAX_NAME_LENGTH, MAX_RANK, Category, CategoryStatus

CATEGORY_EXAMPLE: dict[str, Any] = {"name": "Starters", "rank": 0, "status": "active"}


class CategoryCreate(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/categories``.

    ``rank`` is optional: left out, the section lands at the bottom of the menu, which is
    where a section someone has just thought of belongs.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [CATEGORY_EXAMPLE]})

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    rank: int | None = Field(default=None, ge=0, le=MAX_RANK)
    status: CategoryStatus = CategoryStatus.ACTIVE

    def as_changes(self) -> dict[str, Any]:
        """The fields the caller actually sent."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class CategoryUpdate(BaseModel):
    """Body of ``PATCH /api/v1/tenants/{tenant_id}/categories/{category_id}``.

    Every field is optional; only what is present changes.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [{"rank": 2, "status": "hidden"}]})

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    rank: int | None = Field(default=None, ge=0, le=MAX_RANK)
    status: CategoryStatus | None = None

    def as_changes(self) -> dict[str, Any]:
        """The fields the caller actually sent."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class CategoryOut(BaseModel):
    """One menu category."""

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId
    name: str
    rank: int
    status: CategoryStatus
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_category(cls, category: Category) -> CategoryOut:
        """Project a stored :class:`~app.models.category.Category`."""
        return cls.model_validate(category, from_attributes=True)


class CategoryListResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/{tenant_id}/categories`` - in reading order."""

    categories: list[CategoryOut] = Field(default_factory=list)


__all__ = ["CategoryCreate", "CategoryListResponse", "CategoryOut", "CategoryUpdate"]
