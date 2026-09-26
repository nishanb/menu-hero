"""HTTP schemas of the menu-item and menu-import endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId
from app.models.menu_item import (
    EXPOSURES,
    MAX_NAME_LENGTH,
    MAX_VARIATIONS,
    ORDER_TYPES,
    AddonGroup,
    GstType,
    MenuItem,
    Variation,
)


class VariationOut(BaseModel):
    """One form a dish is sold in, carrying its own price."""

    model_config = ConfigDict(from_attributes=True)

    group: str = ""
    name: str
    price: float = 0
    sap_code: str = ""
    packing_charges: float = 0


class AddonGroupOut(BaseModel):
    """A set of extras offered with a dish."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    selection: str = "single"
    minimum: int = 0
    maximum: int = 1


class MenuItemOut(BaseModel):
    """One dish.

    ``price_from`` is what a menu prints: the item's own price, or the cheapest variation for
    a dish that is priced by its variations.
    """

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId
    name: str
    online_name: str = ""
    description: str = ""
    category: str = ""
    parent_category: str = ""
    short_code: str = ""
    short_code_2: str = ""
    sap_code: str = ""
    hsn_code: str = ""
    diet: str = ""
    price: float = 0
    price_from: float = 0
    packing_charges: float = 0
    profit_margin: float = 0
    weight: float = 0
    weight_unit: str = ""
    gst_type: GstType | None = None
    order_types: list[str] = Field(default_factory=list)
    expose_in: list[str] = Field(default_factory=list)
    allow_decimal_quantity: bool = True
    manufactured_on: datetime | None = None
    expires_on: datetime | None = None
    rank: int = 0
    image_url: str = ""
    is_available: bool = True
    variations: list[VariationOut] = Field(default_factory=list)
    addon_group: AddonGroupOut | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_item(cls, item: MenuItem) -> MenuItemOut:
        """Project a stored :class:`~app.models.menu_item.MenuItem`."""
        return cls(
            id=_require_id(item),
            name=item.name,
            online_name=item.online_name,
            description=item.description,
            category=item.category,
            parent_category=item.parent_category,
            short_code=item.short_code,
            short_code_2=item.short_code_2,
            sap_code=item.sap_code,
            hsn_code=item.hsn_code,
            diet=item.diet,
            price=item.price,
            price_from=item.price_from,
            packing_charges=item.packing_charges,
            profit_margin=item.profit_margin,
            weight=item.weight,
            weight_unit=item.weight_unit,
            gst_type=item.gst_type,
            order_types=list(item.order_types),
            expose_in=list(item.expose_in),
            allow_decimal_quantity=item.allow_decimal_quantity,
            manufactured_on=item.manufactured_on,
            expires_on=item.expires_on,
            rank=item.rank,
            image_url=item.image_url,
            is_available=item.is_available,
            variations=[_variation(v) for v in item.variations],
            addon_group=_addon_group(item.addon_group),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class VariationIn(BaseModel):
    """One form a dish is sold in, as submitted."""

    group: str = Field(default="", max_length=MAX_NAME_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    price: float = Field(default=0, ge=0)
    sap_code: str = Field(default="", max_length=40)
    packing_charges: float = Field(default=0, ge=0)


class AddonGroupIn(BaseModel):
    """A set of extras offered with a dish, as submitted."""

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    selection: str = "single"
    minimum: int = Field(default=0, ge=0, le=99)
    maximum: int = Field(default=1, ge=0, le=99)


class MenuItemWrite(BaseModel):
    """The editable half of a dish - everything the item form collects.

    Shared by create and update so the two cannot drift. The document model
    (:class:`~app.models.menu_item.MenuItem`) is what validates the *contents*; the bounds
    here exist so an oversized body is refused before it reaches the database.
    """

    online_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    parent_category: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    short_code: str | None = Field(default=None, max_length=40)
    short_code_2: str | None = Field(default=None, max_length=40)
    sap_code: str | None = Field(default=None, max_length=40)
    hsn_code: str | None = Field(default=None, max_length=40)
    diet: str | None = Field(default=None, max_length=40)
    price: float | None = Field(default=None, ge=0)
    packing_charges: float | None = Field(
        default=None, ge=0, description="Container charges, in the POS's words."
    )
    profit_margin: float | None = Field(default=None, ge=0, le=100)
    weight: float | None = Field(default=None, ge=0)
    weight_unit: str | None = Field(default=None, max_length=10)
    gst_type: GstType | None = None
    order_types: list[str] | None = Field(default=None, max_length=len(ORDER_TYPES))
    expose_in: list[str] | None = Field(default=None, max_length=len(EXPOSURES))
    allow_decimal_quantity: bool | None = None
    manufactured_on: datetime | None = None
    expires_on: datetime | None = None
    rank: int | None = Field(default=None, ge=0)
    image_url: str | None = Field(default=None, max_length=2000)
    is_available: bool | None = None
    variations: list[VariationIn] | None = Field(default=None, max_length=MAX_VARIATIONS)
    addon_group: AddonGroupIn | None = None

    def as_changes(self) -> dict[str, Any]:
        """The fields the caller actually sent.

        ``exclude_unset`` without ``exclude_none``: for a menu item, ``null`` is a real
        instruction - clearing an expiry date or an add-on group has to be expressible.
        """
        return self.model_dump(exclude_unset=True)


class MenuItemCreate(MenuItemWrite):
    """Body of ``POST /api/v1/tenants/{tenant_id}/menu/items``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"name": "Neer Dosa", "category": "Breakfast", "price": 60, "diet": "veg"}]
        }
    )

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)


class MenuItemUpdate(MenuItemWrite):
    """Body of ``PATCH /api/v1/tenants/{tenant_id}/menu/items/{item_id}``."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"price": 79, "is_available": False}]}
    )

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)


class MenuImageUploadResponse(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/menu/images``.

    A URL and nothing else, because a URL is all an item ever stores - see
    :mod:`app.services.image_store` for why the bytes are not the caller's business.
    """

    url: str = Field(description="Put this in the item's ``image_url``.")
    content_type: str
    size: int


class AvailabilityUpdate(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/menu/availability``.

    Either a list of dishes or a whole section, because those are the two ways a floor
    manager thinks about it: this dish has run out, or the grill is off tonight.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"category": "Sea Food - Chef Special", "on": False}]}
    )

    item_ids: list[PyObjectId] | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    on: bool = Field(description="True puts them back on the menu.")


class AvailabilityResponse(BaseModel):
    """How many dishes changed. Zero is a normal answer - they were already like that."""

    changed: int = 0


class MenuOptionsResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/{tenant_id}/menu/options`` - what the item form offers.

    Served from the backend so the form and the validators cannot drift: every list here is
    the one the document model checks against.
    """

    diets: list[str] = Field(default_factory=list, description="Suggestions; the field is open.")
    order_types: list[str] = Field(default_factory=list)
    exposures: list[str] = Field(default_factory=list)
    weight_units: list[str] = Field(default_factory=list)
    gst_types: list[str] = Field(default_factory=list)


class MenuItemListResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/{tenant_id}/menu/items``."""

    items: list[MenuItemOut] = Field(default_factory=list)
    total: int = 0


class ImportPreviewItem(BaseModel):
    """One row of the file, as it would be stored. Shown before anything is written."""

    name: str
    category: str = ""
    diet: str = ""
    price: float = 0
    variations: int = 0


class MenuImportResponse(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/menu/import``.

    The same shape answers the dry run and the commit; ``committed`` is what tells them
    apart, and it is the field the UI reads before it says anything reassuring.
    """

    committed: bool = Field(
        description="False for a dry run, which writes nothing and only reports."
    )
    item_count: int = Field(description="Items found in the file.")
    skipped: int = Field(default=0, description="Rows with no usable name.")
    warnings: list[str] = Field(
        default_factory=list, description="What could not be made sense of, row by row."
    )
    new_categories: list[str] = Field(
        default_factory=list, description="Sections the file names that this menu does not have."
    )
    existing_categories: list[str] = Field(
        default_factory=list, description="Sections it names that are already here."
    )
    items_replaced: int = Field(
        default=0, description="Items that were on the menu before this import replaced them."
    )
    items_written: int = Field(default=0, description="Items stored. Zero for a dry run.")
    images: int = Field(
        default=0, description="Rows carrying a picture, inline as base64 or as a link."
    )
    sample: list[ImportPreviewItem] = Field(
        default_factory=list, description="The first few rows, so the owner can eyeball them."
    )


def _require_id(item: MenuItem) -> PyObjectId:
    assert item.id is not None, "a stored menu item always has an id"
    return item.id


def _variation(variation: Variation) -> VariationOut:
    return VariationOut.model_validate(variation, from_attributes=True)


def _addon_group(group: AddonGroup | None) -> AddonGroupOut | None:
    return None if group is None else AddonGroupOut.model_validate(group, from_attributes=True)


__all__ = [
    "AddonGroupIn",
    "AvailabilityResponse",
    "AvailabilityUpdate",
    "AddonGroupOut",
    "ImportPreviewItem",
    "MenuImageUploadResponse",
    "MenuImportResponse",
    "MenuItemCreate",
    "MenuItemListResponse",
    "MenuItemOut",
    "MenuItemUpdate",
    "MenuOptionsResponse",
    "VariationIn",
    "VariationOut",
]
