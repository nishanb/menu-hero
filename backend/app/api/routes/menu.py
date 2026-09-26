"""The working menu: its items, and taking a POS export in.

    GET    /api/v1/tenants/{tenant_id}/menu/items            (member)
    GET    /api/v1/tenants/{tenant_id}/menu/options          (member)
    POST   /api/v1/tenants/{tenant_id}/menu/items            (owner or admin)
    PATCH  /api/v1/tenants/{tenant_id}/menu/items/{item_id}  (owner or admin)
    DELETE /api/v1/tenants/{tenant_id}/menu/items/{item_id}  (owner or admin)
    POST   /api/v1/tenants/{tenant_id}/menu/availability     (owner or admin)
    POST   /api/v1/tenants/{tenant_id}/menu/images           (owner or admin)
    POST   /api/v1/tenants/{tenant_id}/menu/import           (owner or admin)

The import is deliberately two calls of the same endpoint. ``dry_run=true`` reads the file
and reports what it found - how many items, which sections are new, what it could not make
sense of - and writes nothing; only ``dry_run=false`` commits. HLD 9.1 puts a person between
an import and a live menu, and a preview that costs one upload is the cheapest way to keep
them there.

Committing **replaces** the item list. An export is somebody saying "this is my menu", and
merging it into what is already there would leave dishes nobody can account for.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from app.dependencies.auth import (
    CurrentUser,
    ImageStoreDep,
    ManagementServiceDep,
    MenuServiceDep,
)
from app.models import PyObjectId
from app.models.menu_item import EXPOSURES, ORDER_TYPES, SUGGESTED_DIETS, WEIGHT_UNITS, GstType
from app.schemas.menu import (
    AvailabilityResponse,
    AvailabilityUpdate,
    ImportPreviewItem,
    MenuImageUploadResponse,
    MenuImportResponse,
    MenuItemCreate,
    MenuItemListResponse,
    MenuItemOut,
    MenuItemUpdate,
    MenuOptionsResponse,
)
from app.services.errors import ValidationFailedError
from app.services.image_store import ImageError
from app.services.menu_import import MAX_UPLOAD_BYTES, MenuImportError, ParsedItem
from app.services.menu_service import ImportSummary

router = APIRouter(prefix="/tenants")

SAMPLE_SIZE = 12
"""Enough rows for an owner to recognise their own menu, few enough to read at a glance."""

FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    403: {"description": "Not an owner of this restaurant"}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {404: {"description": "Restaurant not found"}}


@router.get(
    "/{tenant_id}/menu/items",
    response_model=MenuItemListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="The menu's items",
)
async def list_items(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
) -> MenuItemListResponse:
    """Grouped by section and ranked within it - the order the menu reads in."""
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    items = await menu.list_items(tenant_id)
    return MenuItemListResponse(
        items=[MenuItemOut.from_item(item) for item in items], total=len(items)
    )


@router.get(
    "/{tenant_id}/menu/options",
    response_model=MenuOptionsResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="What the item form offers",
)
async def menu_options(
    tenant_id: PyObjectId, context: CurrentUser, management: ManagementServiceDep
) -> MenuOptionsResponse:
    """The closed sets the item model validates against, plus the open diet suggestions.

    Served rather than repeated in the UI so the form and the validators cannot drift.
    """
    management.assert_member(context, tenant_id)
    return MenuOptionsResponse(
        diets=list(SUGGESTED_DIETS),
        order_types=list(ORDER_TYPES),
        exposures=list(EXPOSURES),
        weight_units=list(WEIGHT_UNITS),
        gst_types=[member.value for member in GstType],
    )


@router.post(
    "/{tenant_id}/menu/items",
    response_model=MenuItemOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "A field was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
    },
    summary="Add a dish (owner or admin)",
)
async def create_item(
    tenant_id: PyObjectId,
    body: MenuItemCreate,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
) -> MenuItemOut:
    """For a restaurant with no export to import, or a dish added after one."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    created = await menu.create_item(
        tenant_id=tenant_id, changes={**body.as_changes(), "name": body.name}, actor=context
    )
    return MenuItemOut.from_item(created)


@router.patch(
    "/{tenant_id}/menu/items/{item_id}",
    response_model=MenuItemOut,
    responses={
        400: {"description": "A field was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
    },
    summary="Edit a dish (owner or admin)",
)
async def update_item(
    tenant_id: PyObjectId,
    item_id: PyObjectId,
    body: MenuItemUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
) -> MenuItemOut:
    """Partial update: only the fields present in the body change."""
    management.assert_can_manage_tenant(context, tenant_id)
    updated = await menu.update_item(
        tenant_id=tenant_id, item_id=item_id, changes=body.as_changes(), actor=context
    )
    return MenuItemOut.from_item(updated)


@router.delete(
    "/{tenant_id}/menu/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Remove a dish (owner or admin)",
)
async def delete_item(
    tenant_id: PyObjectId,
    item_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
) -> Response:
    """Gone from the working menu. Published versions are immutable and keep their copy."""
    management.assert_can_manage_tenant(context, tenant_id)
    await menu.delete_item(tenant_id=tenant_id, item_id=item_id, actor=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/menu/availability",
    response_model=AvailabilityResponse,
    responses={
        400: {"description": "Neither items nor a section were named"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
    },
    summary="Turn dishes on or off (owner or admin)",
)
async def set_availability(
    tenant_id: PyObjectId,
    body: AvailabilityUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
) -> AvailabilityResponse:
    """A service decision, not a menu edit - nothing is published and no version changes."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    changed = await menu.set_availability(
        tenant_id=tenant_id,
        is_available=body.on,
        item_ids=list(body.item_ids) if body.item_ids is not None else None,
        category=body.category,
        actor=context,
    )
    return AvailabilityResponse(changed=changed)


@router.post(
    "/{tenant_id}/menu/images",
    response_model=MenuImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Not an image, or larger than 2 MB"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
    },
    summary="Upload a picture for a dish (owner or admin)",
)
async def upload_image(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    images: ImageStoreDep,
    file: Annotated[UploadFile, File(description="A PNG, JPEG, WEBP or GIF, up to 2 MB.")],
) -> MenuImageUploadResponse:
    """Store a picture and hand back the URL to put on the item.

    Deliberately its own call rather than base64 inside the item body: a 2 MB image inside a
    JSON patch is a 2 MB request that has to be re-sent every time the price changes.
    """
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    payload = await file.read()
    try:
        url = await images.store(
            tenant_id=tenant_id, data=payload, content_type=file.content_type or ""
        )
    except ImageError as exc:
        raise ValidationFailedError(f"That file could not be used: {exc}.") from exc
    return MenuImageUploadResponse(url=url, content_type=file.content_type or "", size=len(payload))


@router.post(
    "/{tenant_id}/menu/import",
    response_model=MenuImportResponse,
    responses={
        400: {"description": "The file could not be read as a menu export"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        413: {"description": "The file is larger than 5 MB"},
    },
    summary="Import a menu from a POS export (owner or admin)",
)
async def import_menu(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    menu: MenuServiceDep,
    file: Annotated[UploadFile, File(description="The POS item export, as CSV.")],
    dry_run: Annotated[
        bool, Query(description="Read and report without writing. Do this first.")
    ] = True,
) -> MenuImportResponse:
    """Read a CSV export; with ``dry_run=false``, make it the menu.

    Every problem the file has is reported rather than raised: one unreadable row out of four
    hundred costs that row, not the import.
    """
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError("That file is too large; the limit is 5 MB.")
    try:
        summary = (
            await menu.preview(tenant_id=tenant_id, payload=payload)
            if dry_run
            else await menu.commit(tenant_id=tenant_id, payload=payload, actor=context)
        )
    except MenuImportError as exc:
        # The parser's own sentence is the one worth showing: it names the column or the row.
        raise ValidationFailedError(str(exc)) from exc
    return _response(summary)


def _price_from(item: ParsedItem) -> float:
    """What the preview shows: the row's price, or the cheapest variation for a dish priced
    by its variations."""
    if item.variations:
        return min(variation.price for variation in item.variations)
    return item.price


def _response(summary: ImportSummary) -> MenuImportResponse:
    """Project an :class:`ImportSummary` for the wire."""
    return MenuImportResponse(
        committed=summary.committed,
        item_count=len(summary.parsed.items),
        skipped=summary.parsed.skipped,
        warnings=summary.parsed.warnings,
        new_categories=summary.new_categories,
        existing_categories=summary.existing_categories,
        items_replaced=summary.items_replaced,
        items_written=summary.items_written,
        images=summary.parsed.images,
        sample=[
            ImportPreviewItem(
                name=item.name,
                category=item.category,
                diet=item.diet,
                price=_price_from(item),
                variations=len(item.variations),
            )
            for item in summary.parsed.items[:SAMPLE_SIZE]
        ],
    )
