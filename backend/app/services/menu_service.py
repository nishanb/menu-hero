"""The working menu: what is on it, and taking an import in.

Two jobs, and the second is the delicate one.

Reading is ordinary. Importing is not: a POS export is a *replacement* menu, not a patch, so
committing one swaps the whole item list. That is why the endpoint has a dry run and the UI
insists on it - :meth:`MenuService.preview` reads the file and reports what it found without
writing a byte, and only a second, explicit call commits.

Pictures come along too, and are the reason :class:`~app.services.image_store.ImageStore`
exists: a cell may carry a whole image as base64, and that is decoded once on the way in and
stored as bytes, never kept as a data URL on four hundred documents.

Categories come along for the ride. The sections named in the export are created if the
restaurant does not already have them, in the order they first appear, because a menu whose
items point at headings that do not exist is not much of a menu. Existing categories are left
exactly as they are - their rank and their hidden/active status are the owner's decisions,
and an import has no business overruling them.
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
from app.models.category import MAX_CATEGORIES_PER_TENANT, Category, CategoryRepository
from app.models.menu_item import MAX_ITEMS_PER_TENANT, MenuItem, MenuItemRepository
from app.services.auth_service import AuthContext
from app.services.errors import NotFoundError, ValidationFailedError
from app.services.image_store import ImageError, ImageStore
from app.services.menu_import import ParsedItem, ParsedMenu, parse_items_csv

logger = logging.getLogger(__name__)

EDITABLE_ITEM_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "online_name",
        "description",
        "category",
        "parent_category",
        "short_code",
        "short_code_2",
        "sap_code",
        "hsn_code",
        "diet",
        "price",
        "packing_charges",
        "profit_margin",
        "weight",
        "weight_unit",
        "gst_type",
        "order_types",
        "expose_in",
        "allow_decimal_quantity",
        "manufactured_on",
        "expires_on",
        "rank",
        "image_url",
        "is_available",
        "variations",
        "addon_group",
    }
)
"""What a create or a patch may set. ``tenant_id`` is fixed; timestamps are ours."""


class ImportSummary:
    """What an import did, or would do. Returned by both the dry run and the commit."""

    def __init__(
        self,
        *,
        parsed: ParsedMenu,
        new_categories: list[str],
        existing_categories: list[str],
        items_written: int = 0,
        items_replaced: int = 0,
        committed: bool = False,
    ) -> None:
        self.parsed = parsed
        self.new_categories = new_categories
        self.existing_categories = existing_categories
        self.items_written = items_written
        self.items_replaced = items_replaced
        self.committed = committed


class MenuService:
    """Use-case layer for ``/tenants/{tenant_id}/menu``."""

    def __init__(self, database: MongoDatabase, *, images: ImageStore) -> None:
        self._items = MenuItemRepository(database)
        self._categories = CategoryRepository(database)
        self._images = images

    async def list_items(self, tenant_id: ObjectId) -> list[MenuItem]:
        """A restaurant's dishes, grouped by section and ranked within it."""
        return await self._items.list_for_tenant(tenant_id)

    async def get_item(self, *, tenant_id: ObjectId, item_id: ObjectId) -> MenuItem:
        """One dish of *this* restaurant, or :class:`NotFoundError`.

        The tenant is checked as well as the id: an item id from another restaurant must read
        as "not found" here rather than being edited across the tenant boundary.
        """
        item = await self._items.get(item_id)
        if item is None or item.tenant_id != tenant_id:
            raise NotFoundError("Menu item not found")
        return item

    async def create_item(
        self, *, tenant_id: ObjectId, changes: Mapping[str, Any], actor: AuthContext
    ) -> MenuItem:
        """Add a dish by hand, for a restaurant that has no export to import."""
        if await self._items.count({"tenant_id": tenant_id}) >= MAX_ITEMS_PER_TENANT:
            raise ValidationFailedError(f"A menu can hold at most {MAX_ITEMS_PER_TENANT} items.")
        accepted = {
            field: value for field, value in changes.items() if field in EDITABLE_ITEM_FIELDS
        }
        item = self._validated({**accepted, "tenant_id": tenant_id})
        item.id = await self._items.insert(item)
        logger.info(
            "menu item created: tenant=%s name=%s by=%s", tenant_id, item.name, actor.user.email
        )
        return item

    async def update_item(
        self,
        *,
        tenant_id: ObjectId,
        item_id: ObjectId,
        changes: Mapping[str, Any],
        actor: AuthContext,
    ) -> MenuItem:
        """Apply a partial update, re-validating the merged document.

        Merged and re-validated rather than ``$set`` as given, the same as everywhere else
        here: a patch must not be able to store what a create would have been refused for.
        """
        current = await self.get_item(tenant_id=tenant_id, item_id=item_id)
        accepted = {
            field: value for field, value in changes.items() if field in EDITABLE_ITEM_FIELDS
        }
        if not accepted:
            return current
        merged = self._validated({**current.model_dump(), **accepted})
        stored = merged.model_dump(include=set(accepted)) | {"updated_at": utcnow()}
        updated = await self._items.update_by_id(item_id, stored)
        if updated is None:
            raise NotFoundError("Menu item not found")
        logger.info(
            "menu item updated: tenant=%s name=%s fields=%s by=%s",
            tenant_id,
            updated.name,
            sorted(accepted),
            actor.user.email,
        )
        return updated

    async def set_availability(
        self,
        *,
        tenant_id: ObjectId,
        is_available: bool,
        item_ids: list[ObjectId] | None,
        category: str | None,
        actor: AuthContext,
    ) -> int:
        """Turn dishes on or off, by id or by whole section.

        Availability is a *service* decision, not a menu edit: it changes what a diner is
        offered tonight and never publishes a new version of the menu. That is why it has its
        own call, and its own page, rather than being a field somebody remembers to patch.
        """
        if item_ids is None and category is None:
            raise ValidationFailedError("Say which dishes to switch: some items, or a section.")
        changed = await self._items.set_available(
            tenant_id, is_available=is_available, item_ids=item_ids, category=category
        )
        logger.info(
            "menu availability set: tenant=%s on=%s changed=%d section=%r by=%s",
            tenant_id,
            is_available,
            changed,
            category,
            actor.user.email,
        )
        return changed

    async def delete_item(
        self, *, tenant_id: ObjectId, item_id: ObjectId, actor: AuthContext
    ) -> None:
        """Remove a dish."""
        item = await self.get_item(tenant_id=tenant_id, item_id=item_id)
        await self._items.delete(item_id)
        logger.info(
            "menu item removed: tenant=%s name=%s by=%s", tenant_id, item.name, actor.user.email
        )

    @staticmethod
    def _validated(document: Mapping[str, Any]) -> MenuItem:
        """Build a :class:`MenuItem`, reporting a refused field as a 400 rather than a 500."""
        try:
            return MenuItem.model_validate(dict(document))
        except ValidationError as exc:
            raise ValidationFailedError(_first_message(exc)) from exc

    async def preview(self, *, tenant_id: ObjectId, payload: bytes) -> ImportSummary:
        """Read a file and report what it holds. Writes nothing."""
        parsed = parse_items_csv(payload)
        new, existing = await self._split_categories(tenant_id, parsed.categories)
        return ImportSummary(parsed=parsed, new_categories=new, existing_categories=existing)

    async def commit(
        self, *, tenant_id: ObjectId, payload: bytes, actor: AuthContext
    ) -> ImportSummary:
        """Read a file and make it the restaurant's menu.

        The item list is replaced outright: an export is somebody saying "this is my menu",
        and merging it into what is already there would leave dishes nobody can account for.
        Categories are only ever added.
        """
        parsed = parse_items_csv(payload)
        new, existing = await self._split_categories(tenant_id, parsed.categories)

        replaced = await self._items.count({"tenant_id": tenant_id})
        images = await self._store_images(tenant_id, parsed)
        items = [
            self._to_item(item, tenant_id=tenant_id, image_url=images.get(item.image, ""))
            for item in parsed.items
        ]
        written = await self._items.replace_all(tenant_id, items)
        await self._create_categories(tenant_id, new)

        logger.info(
            "menu imported: tenant=%s items=%d replaced=%d categories=%d images=%d by=%s",
            tenant_id,
            written,
            replaced,
            len(new),
            len(images),
            actor.user.email,
        )
        return ImportSummary(
            parsed=parsed,
            new_categories=new,
            existing_categories=existing,
            items_written=written,
            items_replaced=replaced,
            committed=True,
        )

    # ------------------------------------------------------------------ helpers

    async def _store_images(self, tenant_id: ObjectId, parsed: ParsedMenu) -> dict[str, str]:
        """Put every distinct picture somewhere and map each cell value to its URL.

        Keyed on the cell rather than the row: a POS export repeats one placeholder across
        dozens of items, and this is what turns dozens of 2 MB decodes into one. An https
        link is already a URL and is passed through untouched - it is somebody's CDN already.

        A picture that will not decode costs that picture. Losing a whole 400-item menu
        because one cell was truncated in a spreadsheet would be the wrong trade.
        """
        urls: dict[str, str] = {}
        for item in parsed.items:
            cell = item.image
            if not cell or cell in urls:
                continue
            if cell.startswith("https://"):
                urls[cell] = cell
                continue
            try:
                urls[cell] = await self._images.store_data_url(tenant_id=tenant_id, data_url=cell)
            except ImageError as exc:
                urls[cell] = ""
                parsed.warn(f"'{item.name[:40]}' has an image that was not stored: {exc}.")
        return urls

    async def _split_categories(
        self, tenant_id: ObjectId, names: list[str]
    ) -> tuple[list[str], list[str]]:
        """Which of the file's sections are new here, and which the restaurant already has."""
        held = {category.name_key for category in await self._categories.list_for_tenant(tenant_id)}
        new: list[str] = []
        existing: list[str] = []
        for name in names:
            (existing if name.casefold() in held else new).append(name)
        return new, existing

    async def _create_categories(self, tenant_id: ObjectId, names: list[str]) -> None:
        """Add the sections the file needs, ranked in the order the file introduces them."""
        start = await self._categories.next_rank(tenant_id)
        room = MAX_CATEGORIES_PER_TENANT - await self._categories.count({"tenant_id": tenant_id})
        for offset, name in enumerate(names[: max(0, room)]):
            try:
                await self._categories.insert(
                    Category(tenant_id=tenant_id, name=name, rank=start + offset)
                )
            except (DuplicateKeyError, ValidationError):
                # Raced with another import, or a heading this model will not accept. Neither
                # is worth losing an otherwise good menu over.
                logger.warning("category '%s' skipped during import for tenant %s", name, tenant_id)

    @staticmethod
    def _to_item(parsed: ParsedItem, *, tenant_id: ObjectId, image_url: str = "") -> MenuItem:
        """One parsed row as a storable item, reporting a refused field as a 400."""
        try:
            return MenuItem(
                tenant_id=tenant_id,
                name=parsed.name,
                online_name=parsed.online_name,
                description=parsed.description,
                category=parsed.category,
                parent_category=parsed.parent_category,
                short_code=parsed.short_code,
                short_code_2=parsed.short_code_2,
                sap_code=parsed.sap_code,
                hsn_code=parsed.hsn_code,
                diet=parsed.diet,
                gst_type=parsed.gst_type or None,
                price=parsed.price,
                packing_charges=parsed.packing_charges,
                rank=parsed.rank,
                image_url=image_url,
                variations=parsed.variations,
                addon_group=parsed.addon_group,
            )
        except ValidationError as exc:
            raise ValidationFailedError(
                f"'{parsed.name[:60]}' could not be stored: {_first_message(exc)}"
            ) from exc


def _first_message(error: ValidationError) -> str:
    """The first validator message, without Pydantic's boilerplate prefix."""
    for item in error.errors():
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            return message
    return "a field was refused"


__all__ = ["ImportSummary", "MenuService"]
