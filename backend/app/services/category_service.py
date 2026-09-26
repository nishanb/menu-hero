"""Menu categories: create, rename, re-order, hide, remove.

Thin on purpose. Unlike the floor plan there is nothing to reconcile here - a category is a
single document an owner edits directly - so the service exists for the three things a route
should not be doing itself: turning a refused field into a 400, turning a duplicate name into
a 409 the owner can act on, and keeping the collection bounded.

Deletion is a real delete. Nothing points at a category yet: HLD 4 stores an item's section
as ``category_path`` text on the published item, so removing a heading here cannot orphan
anything that has already been served to a diner.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.core.database import MongoDatabase
from app.models import utcnow
from app.models.category import (
    MAX_CATEGORIES_PER_TENANT,
    Category,
    CategoryRepository,
)
from app.services.auth_service import AuthContext
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError

logger = logging.getLogger(__name__)

EDITABLE_FIELDS: frozenset[str] = frozenset({"name", "rank", "status"})
"""What a ``PATCH`` may change. ``tenant_id`` is fixed at creation; the rest is derived."""


class CategoryService:
    """Use-case layer for ``/tenants/{tenant_id}/categories``."""

    def __init__(self, database: MongoDatabase) -> None:
        self._categories = CategoryRepository(database)

    async def list(self, tenant_id: ObjectId) -> list[Category]:
        """A restaurant's sections, in reading order."""
        return await self._categories.list_for_tenant(tenant_id)

    async def create(
        self, *, tenant_id: ObjectId, changes: Mapping[str, Any], actor: AuthContext
    ) -> Category:
        """Add a section. Without a rank it goes to the bottom, which is where a new one belongs."""
        if await self._categories.count({"tenant_id": tenant_id}) >= MAX_CATEGORIES_PER_TENANT:
            raise ValidationFailedError(
                f"A menu can have at most {MAX_CATEGORIES_PER_TENANT} categories."
            )
        accepted = {field: value for field, value in changes.items() if field in EDITABLE_FIELDS}
        if accepted.get("rank") is None:
            accepted["rank"] = await self._categories.next_rank(tenant_id)
        category = self._validated({**accepted, "tenant_id": tenant_id})
        try:
            category.id = await self._categories.insert(category)
        except DuplicateKeyError as exc:
            raise ConflictError(_taken(category.name)) from exc
        logger.info(
            "category created: tenant=%s name=%s by=%s", tenant_id, category.name, actor.user.email
        )
        return category

    async def update(
        self,
        *,
        tenant_id: ObjectId,
        category_id: ObjectId,
        changes: Mapping[str, Any],
        actor: AuthContext,
    ) -> Category:
        """Apply a partial update, re-validating the merged document.

        Merged and re-validated rather than ``$set`` as given: a patch must not be able to
        store a name a create would have been refused for.
        """
        current = await self.get(tenant_id=tenant_id, category_id=category_id)
        accepted = {field: value for field, value in changes.items() if field in EDITABLE_FIELDS}
        if not accepted:
            return current
        merged = self._validated({**current.model_dump(), **accepted})
        stored = merged.model_dump(include=set(accepted) | {"name_key"}) | {"updated_at": utcnow()}
        try:
            updated = await self._categories.update_by_id(category_id, stored)
        except DuplicateKeyError as exc:
            raise ConflictError(_taken(merged.name)) from exc
        if updated is None:
            raise NotFoundError("Category not found")
        logger.info(
            "category updated: tenant=%s name=%s fields=%s by=%s",
            tenant_id,
            updated.name,
            sorted(accepted),
            actor.user.email,
        )
        return updated

    async def delete(
        self, *, tenant_id: ObjectId, category_id: ObjectId, actor: AuthContext
    ) -> None:
        """Remove a section."""
        category = await self.get(tenant_id=tenant_id, category_id=category_id)
        await self._categories.delete(category_id)
        logger.info(
            "category removed: tenant=%s name=%s by=%s", tenant_id, category.name, actor.user.email
        )

    async def get(self, *, tenant_id: ObjectId, category_id: ObjectId) -> Category:
        """One section of *this* restaurant, or :class:`NotFoundError`.

        The tenant is checked as well as the id: a category id from another restaurant must
        read as "not found" here rather than being edited across the tenant boundary.
        """
        category = await self._categories.get(category_id)
        if category is None or category.tenant_id != tenant_id:
            raise NotFoundError("Category not found")
        return category

    @staticmethod
    def _validated(document: Mapping[str, Any]) -> Category:
        """Build a :class:`Category`, reporting a refused field as a 400 rather than a 500."""
        try:
            return Category.model_validate(dict(document))
        except ValidationError as exc:
            raise ValidationFailedError(_first_message(exc)) from exc


def _taken(name: str) -> str:
    return f"This menu already has a category called '{name}'."


def _first_message(error: ValidationError) -> str:
    """The first validator message, without Pydantic's boilerplate prefix."""
    for item in error.errors():
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            return message
    return "That category could not be saved"


__all__ = ["CategoryService"]
