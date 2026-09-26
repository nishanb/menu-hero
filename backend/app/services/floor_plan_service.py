"""The floor plan of a restaurant, and the tables it puts on the floor.

The editor is a dirty buffer with Save and Discard, so the write side is one call that
replaces the whole plan. What makes that safe is the split the data model already draws:

* the **plan** is a drawing and is replaced outright on every save;
* a **table** is an identity that outlives the drawing - an order points at it, a QR code
  encodes it - so it is created, renamed and *deactivated*, never deleted.

:meth:`FloorPlanService.save` is the reconciliation between the two. Its three rules, in
the order they matter:

1. a table element the editor already knows the id of keeps that id, whatever it is renamed
   to;
2. a table drawn afresh reuses the row of a table with the same name that was taken off the
   floor earlier, so putting a table back does not invalidate the QR code on it;
3. a table that has left the plan is deactivated, which keeps its past orders resolvable.

Rule 1 is applied to every element before rule 2 is applied to any of them - see
:meth:`FloorPlanService.save` for why one pass is not enough.
"""

from __future__ import annotations

import logging

from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.core.database import MongoDatabase
from app.models import utcnow
from app.models.floor_plan import (
    FloorPlan,
    FloorPlanDraft,
    FloorPlanElement,
    FloorPlanElementDraft,
    FloorPlanRepository,
)
from app.models.table import MAX_TABLES_PER_TENANT, Table, TableRepository
from app.services.auth_service import AuthContext
from app.services.errors import ConflictError, ValidationFailedError

logger = logging.getLogger(__name__)


class FloorPlanService:
    """Use-case layer for ``/tenants/{tenant_id}/floor-plan``."""

    def __init__(self, database: MongoDatabase) -> None:
        self._plans = FloorPlanRepository(database)
        self._tables = TableRepository(database)

    async def get(self, tenant_id: ObjectId) -> tuple[FloorPlan, list[Table]]:
        """The tenant's plan and the tables on it.

        A restaurant that has never opened the editor has no document; an empty plan is
        returned rather than a 404, because "no plan yet" is the ordinary first state and
        the editor needs a canvas to draw on either way.
        """
        plan = await self._plans.get_for_tenant(tenant_id) or FloorPlan(tenant_id=tenant_id)
        tables = await self._tables.list_for_tenant(tenant_id, active_only=True)
        return plan, tables

    async def save(
        self, *, tenant_id: ObjectId, draft: FloorPlanDraft, actor: AuthContext
    ) -> tuple[FloorPlan, list[Table]]:
        """Replace the plan, reconciling the ``tables`` collection with what it draws."""
        drafted = draft.tables()
        self._assert_names_are_distinct(drafted)
        if len(drafted) > MAX_TABLES_PER_TENANT:
            raise ValidationFailedError(
                f"A restaurant can have at most {MAX_TABLES_PER_TENANT} tables."
            )

        existing = await self._tables.list_for_tenant(tenant_id)
        free_by_id = {table.id: table for table in existing if table.id is not None}
        free_by_name = {table.label_key: table for table in existing}

        resolved: dict[str, ObjectId] = {}
        kept: set[ObjectId] = set()

        # Two passes, and the order is what keeps them apart. An element that already knows
        # an id has a definite claim on that row, so those are settled first and their old
        # names released; only then do the rest look for a table by name. In one pass the
        # second element of a rename-and-reuse ("A1" becomes "B1", a new table is called
        # "A1") would find the renamed row still filed under its old name and both elements
        # would resolve to it - one table answering to two places, and the rename lost.
        # Settling the renames first also frees the name before anything tries to take it,
        # which is what stops the unique index refusing the save.
        for element in drafted:
            table = free_by_id.pop(element.table_id, None) if element.table_id else None
            if table is None:
                continue
            free_by_name.pop(table.label_key, None)
            table = await self._update(table, element)
            assert table.id is not None
            resolved[element.id] = table.id
            kept.add(table.id)

        for element in drafted:
            if element.id in resolved:
                continue
            # Rule 2: a table put back on the floor is the same table it was before, so the
            # QR code already printed for it keeps working.
            table = free_by_name.pop(element.label.strip().casefold(), None)
            if table is not None:
                if table.id is not None:
                    free_by_id.pop(table.id, None)
                table = await self._update(table, element)
            else:
                table = await self._create(element, tenant_id=tenant_id)
            assert table.id is not None
            resolved[element.id] = table.id
            kept.add(table.id)

        stored = self._resolve(draft, resolved, tenant_id=tenant_id)
        plan = await self._plans.save_for_tenant(stored)

        gone = [table.id for table in existing if table.id is not None and table.id not in kept]
        removed = await self._tables.deactivate(gone)
        logger.info(
            "floor plan saved: tenant=%s elements=%d tables=%d retired=%d by=%s",
            tenant_id,
            len(plan.elements),
            len(kept),
            removed,
            actor.user.email,
        )
        return plan, await self._tables.list_for_tenant(tenant_id, active_only=True)

    # ------------------------------------------------------------------ reconciliation

    async def _create(self, element: FloorPlanElementDraft, *, tenant_id: ObjectId) -> Table:
        table = self._validated_table(
            {"tenant_id": tenant_id, "label": element.label, "seats": element.seats}
        )
        try:
            table.id = await self._tables.insert(table)
        except DuplicateKeyError as exc:
            raise ConflictError(
                f"Another table here is already called '{element.label}'. Rename one of them."
            ) from exc
        return table

    async def _update(self, table: Table, element: FloorPlanElementDraft) -> Table:
        """Bring a stored table in line with what the editor says about it."""
        wanted = self._validated_table(
            {"tenant_id": table.tenant_id, "label": element.label, "seats": element.seats}
        )
        changes = {
            "label": wanted.label,
            "label_key": wanted.label_key,
            "seats": wanted.seats,
            "is_active": True,
        }
        if all(getattr(table, field) == value for field, value in changes.items()):
            return table
        assert table.id is not None
        try:
            updated = await self._tables.update_by_id(table.id, changes | {"updated_at": utcnow()})
        except DuplicateKeyError as exc:
            # Two tables swapping names in one save land here: the first rename collides
            # with the table still holding the name. Saving the renames one at a time works,
            # and is rare enough not to be worth a two-phase rename.
            raise ConflictError(
                f"Another table here is already called '{element.label}'. Rename one of "
                "them, or save the two changes one at a time."
            ) from exc
        return updated if updated is not None else table

    @staticmethod
    def _resolve(
        draft: FloorPlanDraft, table_ids: dict[str, ObjectId], *, tenant_id: ObjectId
    ) -> FloorPlan:
        """Turn the submitted plan into the stored one, with table names swapped for ids."""
        elements = [
            FloorPlanElement(
                id=element.id,
                kind=element.kind,
                shape=element.shape,
                table_id=table_ids.get(element.id),
                text=element.text,
                x=element.x,
                y=element.y,
                width=element.width,
                height=element.height,
                rotation=element.rotation,
            )
            for element in draft.elements
        ]
        return FloorPlan(
            tenant_id=tenant_id,
            width=draft.width,
            height=draft.height,
            elements=elements,
            updated_at=utcnow(),
        )

    @staticmethod
    def _assert_names_are_distinct(elements: list[FloorPlanElementDraft]) -> None:
        """Two tables on one floor cannot share a name; the diner has to be able to say it."""
        seen: set[str] = set()
        for element in elements:
            key = element.label.strip().casefold()
            if key in seen:
                raise ValidationFailedError(
                    f"Two tables are both called '{element.label}'. Give each one its own name."
                )
            seen.add(key)

    @staticmethod
    def _validated_table(document: dict[str, object]) -> Table:
        """Build a :class:`Table`, reporting a refused field as a 400 rather than a 500."""
        try:
            return Table.model_validate(document)
        except ValidationError as exc:
            raise ValidationFailedError(_first_message(exc)) from exc


def _first_message(error: ValidationError) -> str:
    """The first validator message, without Pydantic's boilerplate prefix."""
    for item in error.errors():
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            return message
    return "That floor plan could not be saved"


__all__ = ["FloorPlanService"]
