"""Platform-level user administration.

    GET   /api/v1/users                  (admin)
    PATCH /api/v1/users/{user_id}/role   (admin)

Only the platform role (``admin`` / ``user``) is set here. ``owner`` and ``staff`` belong
to a restaurant, so they are changed through ``/api/v1/tenants/{id}/members/{user_id}``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies.auth import ManagementServiceDep, PlatformAdmin
from app.models import PyObjectId
from app.schemas.auth import UserOut
from app.schemas.management import PlatformRoleUpdate, UserListResponse

router = APIRouter(prefix="/users")


@router.get("", response_model=UserListResponse, summary="Everyone who has signed in (admin only)")
async def list_users(admin: PlatformAdmin, management: ManagementServiceDep) -> UserListResponse:
    """Newest registrations first."""
    users = await management.list_users()
    return UserListResponse(users=[UserOut.from_user(user) for user in users])


@router.patch(
    "/{user_id}/role",
    response_model=UserOut,
    responses={
        403: {"description": "Not a platform admin, or changing your own role"},
        404: {"description": "User not found"},
        409: {"description": "The last platform admin cannot be demoted"},
    },
    summary="Change a person's platform role (admin only)",
)
async def change_platform_role(
    user_id: PyObjectId,
    body: PlatformRoleUpdate,
    admin: PlatformAdmin,
    management: ManagementServiceDep,
) -> UserOut:
    """Takes effect on the target's next request - sessions carry no cached role."""
    user = await management.change_platform_role(user_id=user_id, role=body.role, actor=admin)
    return UserOut.from_user(user)
