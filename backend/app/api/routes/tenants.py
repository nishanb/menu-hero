"""Restaurants, their team, and invitations.

    POST   /api/v1/tenants                                 (any signed-in person)
    GET    /api/v1/tenants                                 (the caller's restaurants)
    GET    /api/v1/tenants/options                         (what the onboarding form offers)
    GET    /api/v1/tenants/{tenant_id}                     (member)
    PATCH  /api/v1/tenants/{tenant_id}                     (owner or admin)
    PUT    /api/v1/tenants/{tenant_id}/current             (member; remember this one)
    GET    /api/v1/tenants/{tenant_id}/members             (member)
    PATCH  /api/v1/tenants/{tenant_id}/members/{user_id}   (owner or admin)
    DELETE /api/v1/tenants/{tenant_id}/members/{user_id}   (owner or admin)
    POST   /api/v1/tenants/{tenant_id}/invites             (owner or admin)
    GET    /api/v1/tenants/{tenant_id}/invites             (owner or admin)
    DELETE /api/v1/tenants/{tenant_id}/invites/{invite_id} (owner or admin)

Authorisation is two-layered: the dependency proves *who* is calling, and the service's
``assert_can_manage_tenant`` / ``assert_member`` prove they may act on *this* tenant.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.dependencies.auth import CurrentUser, ManagementServiceDep
from app.dependencies.settings import SettingsDep
from app.models import SUGGESTED_DIET_OPTIONS, SUGGESTED_SERVICES, PyObjectId
from app.schemas.management import (
    InviteCreate,
    InviteCreatedResponse,
    InviteListResponse,
    InviteOut,
    MemberListResponse,
    MemberOut,
    MemberRoleUpdate,
    RestaurantOptionsResponse,
    TenantCreate,
    TenantListResponse,
    TenantOut,
    TenantUpdate,
)

router = APIRouter(prefix="/tenants")

INVITE_ACCEPT_PATH = "/invite"
"""Frontend route that takes an invite token and posts it to ``/auth/invites/accept``."""

FORBIDDEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    403: {"description": "Not an owner of this restaurant"}
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"description": "Tenant, member or invite not found"}
}


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "A field was refused (bad logo, oversized property, ...)"},
        404: {"description": "owner_email names nobody who has signed in"},
        409: {"description": "The restaurant could not be created; try again"},
    },
    summary="Create a restaurant",
)
async def create_tenant(
    body: TenantCreate, context: CurrentUser, management: ManagementServiceDep
) -> TenantOut:
    """Whoever creates a restaurant owns it.

    Open to any signed-in person, which is a deliberate departure from HLD 3.1 - onboarding
    has to work for someone who has just signed in and belongs to nothing. ``owner_email``
    stays admin-only and is ignored for everyone else, so nobody can create a restaurant in
    another person's name.
    """
    tenant = await management.create_restaurant(
        name=body.name,
        actor=context,
        profile=body.as_changes(),
        owner_email=body.owner_email,
    )
    return TenantOut.from_tenant(tenant)


@router.get("", response_model=TenantListResponse, summary="Restaurants the caller belongs to")
async def list_tenants(
    context: CurrentUser, management: ManagementServiceDep
) -> TenantListResponse:
    """Every restaurant for an admin; the caller's own memberships for anyone else.

    Also says which one to open on, so the app does not have to guess and then correct
    itself once the memberships arrive. Logos are omitted; fetch one restaurant to get its.
    """
    tenants = await management.list_tenants_for(context)
    return TenantListResponse(
        tenants=[TenantOut.from_tenant(t) for t in tenants],
        active_tenant_id=management.resolve_active_tenant(context),
    )


@router.get(
    "/options",
    response_model=RestaurantOptionsResponse,
    summary="Suggested services and diet options",
)
async def restaurant_options(context: CurrentUser) -> RestaurantOptionsResponse:
    """What the onboarding form offers as chips.

    Suggestions only: both fields accept anything a restaurant types, so this list exists
    to save typing, not to constrain it. Served from the backend so the two do not drift.

    Declared before ``/{tenant_id}``: FastAPI matches in declaration order, and an
    ``ObjectId`` path parameter would otherwise swallow "options" and answer 422.
    """
    return RestaurantOptionsResponse(
        services=list(SUGGESTED_SERVICES), diet_options=list(SUGGESTED_DIET_OPTIONS)
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="One restaurant",
)
async def get_tenant(
    tenant_id: PyObjectId, context: CurrentUser, management: ManagementServiceDep
) -> TenantOut:
    """Readable by any member of the tenant, and by a platform admin. Carries the logo."""
    management.assert_member(context, tenant_id)
    return TenantOut.from_tenant(await management.get_tenant(tenant_id))


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    responses={
        400: {"description": "A field was refused (bad logo, oversized property, ...)"},
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
    },
    summary="Edit a restaurant (owner or admin)",
)
async def update_tenant(
    tenant_id: PyObjectId,
    body: TenantUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
) -> TenantOut:
    """Partial update: only the fields present in the body change.

    ``slug`` is not editable - it is the restaurant's stable handle, and links already
    point at it.
    """
    management.assert_can_manage_tenant(context, tenant_id)
    tenant = await management.update_restaurant(
        tenant_id=tenant_id, changes=body.as_changes(), actor=context
    )
    return TenantOut.from_tenant(tenant)


@router.put(
    "/{tenant_id}/current",
    response_model=TenantOut,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Switch to this restaurant (member)",
)
async def select_tenant(
    tenant_id: PyObjectId, context: CurrentUser, management: ManagementServiceDep
) -> TenantOut:
    """Remember the restaurant the caller is working on, across devices and sessions.

    A preference, never a grant: every read of it is re-checked against the memberships, so
    remembering a restaurant somebody is later removed from grants them nothing.
    """
    tenant = await management.set_last_tenant(tenant_id=tenant_id, actor=context)
    return TenantOut.from_tenant(tenant)


@router.get(
    "/{tenant_id}/members",
    response_model=MemberListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="The restaurant's team",
)
async def list_members(
    tenant_id: PyObjectId, context: CurrentUser, management: ManagementServiceDep
) -> MemberListResponse:
    """Owners and staff, with the person behind each membership."""
    management.assert_member(context, tenant_id)
    await management.get_tenant(tenant_id)
    members = await management.list_members(tenant_id)
    return MemberListResponse(members=[MemberOut.from_membership(m, u) for m, u in members])


@router.patch(
    "/{tenant_id}/members/{user_id}",
    response_model=MemberOut,
    responses={
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        409: {"description": "The last owner cannot be demoted"},
    },
    summary="Change a member's role (owner or admin)",
)
async def change_member_role(
    tenant_id: PyObjectId,
    user_id: PyObjectId,
    body: MemberRoleUpdate,
    context: CurrentUser,
    management: ManagementServiceDep,
) -> MemberOut:
    """Move someone between ``owner`` and ``staff`` at this restaurant."""
    management.assert_can_manage_tenant(context, tenant_id)
    membership = await management.change_member_role(
        tenant_id=tenant_id, user_id=user_id, role=body.role, actor=context
    )
    return MemberOut.from_membership(membership, await management.get_user(user_id))


@router.delete(
    "/{tenant_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        409: {"description": "The last owner cannot be removed"},
    },
    summary="Remove a member (owner or admin)",
)
async def remove_member(
    tenant_id: PyObjectId,
    user_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
) -> Response:
    """The person keeps their account; they just stop being part of this restaurant."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.remove_member(tenant_id=tenant_id, user_id=user_id, actor=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/invites",
    response_model=InviteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **FORBIDDEN_RESPONSE,
        **NOT_FOUND_RESPONSE,
        409: {"description": "Already a member, or an invite is already pending"},
    },
    summary="Invite someone to collaborate (owner or admin)",
)
async def create_invite(
    tenant_id: PyObjectId,
    body: InviteCreate,
    context: CurrentUser,
    management: ManagementServiceDep,
    settings: SettingsDep,
) -> InviteCreatedResponse:
    """Create a pending invite and return its one-time link.

    Nothing is emailed in v1 - the response carries the token so the management UI can show
    or send the link. The membership itself is created only when the invited person signs
    in with Google and proves that email address.
    """
    management.assert_can_manage_tenant(context, tenant_id)
    invite, token = await management.invite_member(
        tenant_id=tenant_id, email=body.email, role=body.role, actor=context
    )
    return InviteCreatedResponse(
        invite=InviteOut.from_invite(invite),
        token=token,
        accept_url=f"{settings.frontend_base_url}{INVITE_ACCEPT_PATH}?token={token}",
    )


@router.get(
    "/{tenant_id}/invites",
    response_model=InviteListResponse,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Pending invites (owner or admin)",
)
async def list_invites(
    tenant_id: PyObjectId, context: CurrentUser, management: ManagementServiceDep
) -> InviteListResponse:
    """Invites that have not been accepted and have not expired."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.get_tenant(tenant_id)
    invites = await management.list_invites(tenant_id)
    return InviteListResponse(invites=[InviteOut.from_invite(i) for i in invites])


@router.delete(
    "/{tenant_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**FORBIDDEN_RESPONSE, **NOT_FOUND_RESPONSE},
    summary="Withdraw a pending invite (owner or admin)",
)
async def revoke_invite(
    tenant_id: PyObjectId,
    invite_id: PyObjectId,
    context: CurrentUser,
    management: ManagementServiceDep,
) -> Response:
    """Deletes the invite, which makes its link stop working immediately."""
    management.assert_can_manage_tenant(context, tenant_id)
    await management.revoke_invite(tenant_id=tenant_id, invite_id=invite_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
