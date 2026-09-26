"""The sections a restaurant's menu is read in.

    GET    /api/v1/tenants/{tenant_id}/categories                (member)
    POST   /api/v1/tenants/{tenant_id}/categories                (owner or admin)
    PATCH  /api/v1/tenants/{tenant_id}/categories/{category_id}  (owner or admin)
    DELETE /api/v1/tenants/{tenant_id}/categories/{category_id}  (owner or admin)

Reading is open to any member - a server needs to know what the menu is organised into -
while the headings themselves are an owner's to set, like the rest of the restaurant's setup.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.dependencies.auth import CategoryServiceDep, CurrentUser, ManagementServiceDep
from app.models import PyObjectId
from app.schemas.category import (
    CategoryCreate,
    CategoryListResponse,
    CategoryOut,
    CategoryUpdate,
)

router = APIRouter(prefix="/tenants")

FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    403: {"description": "Not an owner of this restaurant"}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"description": "Restaurant or category not found"}
}
CONFLICT_RESPONSE: dict[int | str, dict[str, Any]] = {
    409: {"description": "A category with that name already exists here"}
}


@router.get(
    "/{tenant_id}/categories",
    response_model=CategoryListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="The menu's categories, in reading order",
)
async def list_categories(
    tenant_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    categories: CategoryServiceDep,
) -> CategoryListResponse:
    """Hidden categories are included: this is the owner's list, not the diner's menu."""
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    found = await categories.list(tenant_id)
    return CategoryListResponse(categories=[CategoryOut.from_category(c) for c in found])


@router.post(
    "/{tenant_id}/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "A field was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        **CONFLICT_RESPONSE,
    },
    summary="Add a category (owner or admin)",
)
async def create_category(
    tenant_id: PyObjectId,
    body: CategoryCreate,
    context: CurrentUser,
    management: ManagementServiceDep,
    categories: CategoryServiceDep,
) -> CategoryOut:
    """Without a rank the new section goes to the bottom of the menu."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    created = await categories.create(tenant_id=tenant_id, changes=body.as_changes(), actor=context)
    return CategoryOut.from_category(created)


@router.patch(
    "/{tenant_id}/categories/{category_id}",
    response_model=CategoryOut,
    responses={
        400: {"description": "A field was refused"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        **CONFLICT_RESPONSE,
    },
    summary="Rename, re-order or hide a category (owner or admin)",
)
async def update_category(
    tenant_id: PyObjectId,
    category_id: PyObjectId,
    body: CategoryUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
    categories: CategoryServiceDep,
) -> CategoryOut:
    """Partial update: only the fields present in the body change."""
    management.assert_can_manage_tenant(context, tenant_id)
    updated = await categories.update(
        tenant_id=tenant_id, category_id=category_id, changes=body.as_changes(), actor=context
    )
    return CategoryOut.from_category(updated)


@router.delete(
    "/{tenant_id}/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Remove a category (owner or admin)",
)
async def delete_category(
    tenant_id: PyObjectId,
    category_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
    categories: CategoryServiceDep,
) -> Response:
    """A real delete: nothing points at a category, so there is nothing to orphan."""
    management.assert_can_manage_tenant(context, tenant_id)
    await categories.delete(tenant_id=tenant_id, category_id=category_id, actor=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
