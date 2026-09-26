"""Menu items - the dishes a diner reads and orders.

The editable side of HLD 4's ``items``. The published side of that collection is immutable
and tagged with a ``menu_version``; this is the working copy an owner maintains and an
import writes into, before any of it is published.

The shape is the one a real POS export carries, because that is where most menus arrive
from: a name and a price, the section it sits in, a dietary attribute, and - for a dish sold
in more than one form - a list of variations that carry the price instead of the item. An
item with variations has ``price`` 0 and is priced by the cheapest of them, which is what a
menu prints as "from ₹169".

Everything here is tenant-authored data, never instructions (HLD trust boundary), so the
validators are about size and shape only.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_CODE_LENGTH = 40
MAX_PRICE = 1_000_000.0
MAX_RANK = 9999
MAX_VARIATIONS = 20
MAX_ITEMS_PER_TENANT = 5000
"""A ceiling, not a target. The export this was built against carries 407."""

DIET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 -]{0,38}[a-z0-9]$")
"""Same shape as a tenant's ``diet_options``: open, because the next POS will invent one."""

SUGGESTED_DIETS: tuple[str, ...] = ("veg", "non-veg", "egg")
"""What the form offers. The field stays open - an import may carry something else."""

ORDER_TYPES: tuple[str, ...] = ("delivery", "pickup", "dine-in")
"""How a dish may be ordered. Closed: each one is a different price and tax treatment."""

EXPOSURES: tuple[str, ...] = ("online-orders", "captain-app", "kiosk", "other")
"""Where a dish is offered. Closed for the same reason."""

WEIGHT_UNITS: tuple[str, ...] = ("g", "kg", "ml", "l", "piece")
"""Units a portion is measured in. Empty is normal - most dishes are not weighed."""


class GstType(StrEnum):
    """How a dish is taxed. A restaurant meal is a service; a packaged item is goods."""

    SERVICES = "services"
    GOODS = "goods"


def _closed_list(value: object, allowed: tuple[str, ...], label: str) -> object:
    """Lower-case, de-duplicate and check a multiple-choice field against its set."""
    if not isinstance(value, list):
        return value
    chosen: list[str] = []
    for raw in value:
        option = str(raw).strip().lower()
        if not option:
            continue
        if option not in allowed:
            raise ValueError(f"'{raw}' is not one of the {label} options")
        if option not in chosen:
            chosen.append(option)
    return chosen


def _clean(value: object, *, limit: int) -> object:
    """Collapse whitespace and trim to ``limit``; anything not a string is left alone."""
    if not isinstance(value, str):
        return value
    return re.sub(r"\s+", " ", value.strip())[:limit]


class Variation(BaseModel):
    """One form a dish is sold in - Boiled Rice, White Rice - carrying its own price."""

    model_config = ConfigDict(extra="ignore")

    group: str = Field(default="", max_length=MAX_NAME_LENGTH)
    name: str = Field(max_length=MAX_NAME_LENGTH)
    price: float = Field(default=0, ge=0, le=MAX_PRICE)
    sap_code: str = Field(default="", max_length=MAX_CODE_LENGTH)
    packing_charges: float = Field(default=0, ge=0, le=MAX_PRICE)

    @field_validator("group", "name", "sap_code", mode="before")
    @classmethod
    def _tidy(cls, value: object) -> object:
        return _clean(value, limit=MAX_NAME_LENGTH)


class AddonGroup(BaseModel):
    """A set of extras offered with a dish, e.g. how the fish is cooked."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=MAX_NAME_LENGTH)
    selection: str = Field(
        default="single",
        description="'single' or 'multiple' - how many of the group a diner may pick.",
    )
    minimum: int = Field(default=0, ge=0, le=99)
    maximum: int = Field(default=1, ge=0, le=99)

    @field_validator("name", mode="before")
    @classmethod
    def _tidy(cls, value: object) -> object:
        return _clean(value, limit=MAX_NAME_LENGTH)

    @field_validator("selection", mode="before")
    @classmethod
    def _normalise_selection(cls, value: object) -> object:
        """POS exports write ``S``/``M``; the document says which it means."""
        if not isinstance(value, str):
            return value
        letter = value.strip().lower()
        if letter in {"s", "single"}:
            return "single"
        if letter in {"m", "multiple"}:
            return "multiple"
        return "single"


class MenuItem(MongoDocument):
    """One dish on one restaurant's menu."""

    tenant_id: PyObjectId
    name: str = Field(max_length=MAX_NAME_LENGTH)
    online_name: str = Field(default="", max_length=MAX_NAME_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    category: str = Field(default="", max_length=MAX_NAME_LENGTH)
    parent_category: str = Field(default="", max_length=MAX_NAME_LENGTH)
    short_code: str = Field(default="", max_length=MAX_CODE_LENGTH)
    short_code_2: str = Field(default="", max_length=MAX_CODE_LENGTH)
    sap_code: str = Field(default="", max_length=MAX_CODE_LENGTH)
    hsn_code: str = Field(default="", max_length=MAX_CODE_LENGTH)
    diet: str = Field(default="", description="veg, non-veg, egg - open, like the tenant's list.")
    price: float = Field(default=0, ge=0, le=MAX_PRICE)
    packing_charges: float = Field(
        default=0, ge=0, le=MAX_PRICE, description="Container charges, in the POS's words."
    )
    profit_margin: float = Field(default=0, ge=0, le=100, description="Percent.")
    weight: float = Field(default=0, ge=0, le=100_000, description="Portion size; 0 when unset.")
    weight_unit: str = Field(default="", max_length=10)
    gst_type: GstType | None = Field(
        default=None, description="How it is taxed. None until somebody says."
    )
    order_types: list[str] = Field(
        default_factory=list, description="delivery, pickup, dine-in. Empty means all of them."
    )
    expose_in: list[str] = Field(
        default_factory=list, description="Where it is offered: online-orders, captain-app, ..."
    )
    allow_decimal_quantity: bool = Field(
        default=True, description="False for things sold whole, like a bottle."
    )
    manufactured_on: datetime | None = None
    expires_on: datetime | None = None
    rank: int = Field(default=0, ge=0, le=MAX_RANK)
    image_url: str = Field(
        default="",
        max_length=2000,
        description="Where the picture is served from. A URL, never the bytes - see "
        "``app.services.image_store``.",
    )
    is_available: bool = Field(
        default=True, description="Off when the kitchen has run out; see Menu on/off."
    )
    variations: list[Variation] = Field(default_factory=list, max_length=MAX_VARIATIONS)
    addon_group: AddonGroup | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    @field_validator("name", "online_name", "category", "parent_category", mode="before")
    @classmethod
    def _tidy_name(cls, value: object) -> object:
        return _clean(value, limit=MAX_NAME_LENGTH)

    @field_validator("description", mode="before")
    @classmethod
    def _tidy_description(cls, value: object) -> object:
        return _clean(value, limit=MAX_DESCRIPTION_LENGTH)

    @field_validator("order_types", mode="before")
    @classmethod
    def _validate_order_types(cls, value: object) -> object:
        return _closed_list(value, ORDER_TYPES, "order type")

    @field_validator("expose_in", mode="before")
    @classmethod
    def _validate_expose_in(cls, value: object) -> object:
        return _closed_list(value, EXPOSURES, "exposure")

    @field_validator("weight_unit", mode="before")
    @classmethod
    def _validate_weight_unit(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        unit = value.strip().lower()
        if unit and unit not in WEIGHT_UNITS:
            raise ValueError(f"'{value}' is not a unit a portion is measured in")
        return unit

    @field_validator("image_url", mode="before")
    @classmethod
    def _validate_image_url(cls, value: object) -> object:
        """Only ``https://`` or our own ``/api/v1/images/...``.

        The field is rendered as an ``<img src>``, so a ``javascript:`` or ``data:`` value
        here would be stored XSS - which is the whole point of the check. A leading ``/`` is
        this deployment's own image route, whose prefix is configurable, so it is matched by
        shape rather than by a literal path. Base64 never reaches this field: the import
        decodes it and stores the bytes, and what lands here is the URL they are served at.
        """
        if not isinstance(value, str):
            return value
        url = value.strip()
        if url and not (url.startswith("https://") or url.startswith("/")):
            raise ValueError("an image must be an https:// link")
        return url

    @field_validator("short_code", "sap_code", "hsn_code", mode="before")
    @classmethod
    def _tidy_code(cls, value: object) -> object:
        return _clean(value, limit=MAX_CODE_LENGTH)

    @field_validator("diet", mode="before")
    @classmethod
    def _normalise_diet(cls, value: object) -> object:
        """Lower-cased and bounded, or dropped: an unreadable attribute is not worth a 400."""
        if not isinstance(value, str):
            return value
        diet = re.sub(r"\s+", " ", value.strip().lower())
        return diet if DIET_PATTERN.match(diet) else ""

    @model_validator(mode="after")
    def _check_name(self) -> Self:
        if not self.name:
            raise ValueError("a menu item needs a name")
        return self

    @property
    def price_from(self) -> float:
        """What the menu prints: the item's own price, or the cheapest variation."""
        if self.variations:
            return min(variation.price for variation in self.variations)
        return self.price


class MenuItemRepository(MongoRepository[MenuItem]):
    """``menu_items`` - the editable working copy, one document per dish."""

    collection_name = "menu_items"
    document_type = MenuItem

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("category", ASCENDING), ("rank", ASCENDING)],
                    name="ix_tenant_category_rank",
                ),
                IndexModel([("tenant_id", ASCENDING), ("name", ASCENDING)], name="ix_tenant_name"),
            ]
        )

    async def list_for_tenant(self, tenant_id: PyObjectId, *, limit: int = 0) -> list[MenuItem]:
        """A restaurant's dishes, grouped by section and in rank order within it."""
        return await self.find(
            {"tenant_id": tenant_id},
            limit=limit,
            sort=[("category", ASCENDING), ("rank", ASCENDING), ("name", ASCENDING)],
        )

    async def set_available(
        self,
        tenant_id: PyObjectId,
        *,
        is_available: bool,
        item_ids: list[PyObjectId] | None = None,
        category: str | None = None,
    ) -> int:
        """Switch a set of dishes on or off in one write; returns how many changed.

        One update rather than a request per dish: a section of a real menu runs to 28 items,
        and turning it off at the start of service should be one decision and one round trip.
        The tenant is part of the filter, not just the ids, so a stray id from another
        restaurant matches nothing rather than being switched.
        """
        criteria: dict[str, Any] = {"tenant_id": tenant_id, "is_available": not is_available}
        if item_ids is not None:
            criteria["_id"] = {"$in": item_ids}
        if category is not None:
            criteria["category"] = category
        result = await self.collection.update_many(
            criteria, {"$set": {"is_available": is_available, "updated_at": utcnow()}}
        )
        return result.modified_count

    async def replace_all(self, tenant_id: PyObjectId, items: list[MenuItem]) -> int:
        """Swap a restaurant's whole item list for a new one; returns how many were written.

        Delete-then-insert, in that order and not in a transaction: local MongoDB is often a
        standalone server. The window between the two is why the route calls this only for a
        deliberate, confirmed import rather than on any incidental save.
        """
        await self.collection.delete_many({"tenant_id": tenant_id})
        if not items:
            return 0
        result = await self.collection.insert_many([item.to_mongo() for item in items])
        return len(result.inserted_ids)


__all__ = [
    "EXPOSURES",
    "MAX_ITEMS_PER_TENANT",
    "MAX_NAME_LENGTH",
    "MAX_VARIATIONS",
    "ORDER_TYPES",
    "SUGGESTED_DIETS",
    "WEIGHT_UNITS",
    "AddonGroup",
    "GstType",
    "MenuItem",
    "MenuItemRepository",
    "Variation",
]
