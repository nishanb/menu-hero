"""Restaurants, memberships, platform roles and invites - the management flow.

Everything an owner or an admin does to a restaurant or to *other people* lives here. The
service takes the caller's :class:`~app.services.auth_service.AuthContext` for every
mutation, so the rules that keep the system from locking itself out are enforced in one
place rather than in each route:

* an admin cannot change their own platform role, and the last admin cannot be demoted;
* a tenant always keeps at least one owner;
* whoever creates a restaurant owns it, and only an admin may hand it to someone else.

**Deviation from HLD 3.1**, deliberate: the HLD says tenants are operator-created with no
self-serve signup. Onboarding needs someone who has just signed in and belongs to nothing
to be able to create their first restaurant, so :meth:`ManagementService.create_restaurant`
is open to any signed-in person and makes *them* the owner. The admin-only part that
survives is seeding a restaurant for somebody else (``owner_email``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.database import MongoDatabase
from app.core.security import generate_token, hash_token
from app.models import (
    Invite,
    InviteRepository,
    Membership,
    MembershipRepository,
    PlatformRole,
    SlugAllocator,
    Tenant,
    TenantRepository,
    TenantRole,
    User,
    UserRepository,
    utcnow,
)
from app.services.auth_service import AuthContext
from app.services.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)

logger = logging.getLogger(__name__)

EDITABLE_TENANT_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "location_url",
        "logo",
        "services",
        "diet_options",
        "extras",
        "pos",
        "is_active",
    }
)
"""What an owner may change on a restaurant. ``slug`` is stable and ``google_location`` is
set by the import, so neither is accepted from a request body."""


class ManagementService:
    """Use-case layer for the ``/tenants`` and ``/users`` endpoints."""

    def __init__(self, database: MongoDatabase, *, settings: Settings) -> None:
        self._settings = settings
        self._users = UserRepository(database)
        self._tenants = TenantRepository(database)
        self._memberships = MembershipRepository(database)
        self._invites = InviteRepository(database)

    # ------------------------------------------------------------------ restaurants

    async def create_restaurant(
        self,
        *,
        name: str,
        actor: AuthContext,
        profile: Mapping[str, Any] | None = None,
        owner_email: str | None = None,
        google_location: str | None = None,
    ) -> Tenant:
        """Create a restaurant and give it exactly one owner.

        The slug is derived from ``name`` by :class:`~app.models.tenant.SlugAllocator`:
        onboarding asks for a name, not a handle, and two restaurants called "Spice Garden"
        must both be able to exist.

        ``owner_email`` is admin-only and ignored for anyone else - without that rule any
        signed-in person could create a restaurant owned by somebody else. Everyone else
        becomes the owner of what they create.

        Tenant and membership are two writes and local MongoDB is often a standalone
        server, so there is no transaction to lean on: a failed membership insert deletes
        the tenant again rather than leaving an ownerless restaurant nobody can see or
        remove.
        """
        owner = await self._resolve_new_owner(actor=actor, owner_email=owner_email)
        tenant = self._validated_tenant(
            {
                **dict(profile or {}),
                "name": name,
                "slug": await SlugAllocator(self._tenants).allocate(name),
                "google_location": google_location,
            }
        )
        try:
            tenant.id = await self._tenants.insert(tenant)
        except DuplicateKeyError as exc:
            raise ConflictError("That restaurant already exists. Refresh and try again.") from exc

        assert tenant.id is not None and owner.id is not None
        try:
            await self._memberships.insert(
                Membership(
                    tenant_id=tenant.id,
                    user_id=owner.id,
                    role=TenantRole.OWNER,
                    invited_by=actor.user_id if owner.id != actor.user_id else None,
                )
            )
        except Exception:
            await self._tenants.delete(tenant.id)
            logger.exception("rolled back tenant %s: its owner membership failed", tenant.slug)
            raise
        await self._users.set_last_tenant(owner.id, tenant.id)
        logger.info("restaurant created: slug=%s owner=%s", tenant.slug, owner.email)
        return tenant

    async def _resolve_new_owner(self, *, actor: AuthContext, owner_email: str | None) -> User:
        """Who will own the restaurant about to be created."""
        if not owner_email or not actor.is_platform_admin:
            return actor.user
        owner = await self._users.get_by_email(owner_email)
        if owner is None:
            raise NotFoundError(
                f"Nobody has signed in with {owner_email} yet. Create the restaurant and "
                "invite them instead."
            )
        return owner

    async def update_restaurant(
        self, *, tenant_id: ObjectId, changes: Mapping[str, Any], actor: AuthContext
    ) -> Tenant:
        """Apply a partial update to a restaurant's profile.

        The merged document is re-validated through :class:`~app.models.tenant.Tenant`, so
        a patch cannot get a value past the validators that a create would be refused for.
        """
        current = await self.get_tenant(tenant_id)
        accepted = {
            field: value for field, value in changes.items() if field in EDITABLE_TENANT_FIELDS
        }
        if not accepted:
            return current
        merged = self._validated_tenant({**current.model_dump(), **accepted})
        stored = merged.model_dump(include=set(accepted)) | {"updated_at": utcnow()}
        updated = await self._tenants.update_by_id(tenant_id, stored)
        if updated is None:
            raise NotFoundError("Restaurant not found")
        logger.info(
            "restaurant updated: slug=%s fields=%s by=%s",
            updated.slug,
            sorted(accepted),
            actor.user.email,
        )
        return updated

    @staticmethod
    def _validated_tenant(document: Mapping[str, Any]) -> Tenant:
        """Build a :class:`Tenant`, reporting a refused field as a 400 rather than a 500."""
        try:
            return Tenant.model_validate(dict(document))
        except ValidationError as exc:
            raise ValidationFailedError(_first_message(exc)) from exc

    async def get_tenant(self, tenant_id: ObjectId) -> Tenant:
        """Return one restaurant or raise :class:`NotFoundError`."""
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError("Restaurant not found")
        return tenant

    async def list_tenants(self) -> list[Tenant]:
        """Every restaurant, without logos (admin only)."""
        return await self._tenants.find_summaries()

    async def list_tenants_for(self, context: AuthContext) -> list[Tenant]:
        """The restaurants the caller belongs to, without logos (all of them for an admin)."""
        if context.is_platform_admin:
            return await self.list_tenants()
        tenant_ids = [membership.tenant_id for membership in context.memberships]
        if not tenant_ids:
            return []
        return await self._tenants.find_summaries({"_id": {"$in": tenant_ids}})

    # ------------------------------------------------------------------ the current restaurant

    def resolve_active_tenant(self, context: AuthContext) -> ObjectId | None:
        """Which restaurant to open the app on: the last chosen one, else the first held.

        ``users.last_tenant_id`` is a preference, never a grant, so it is checked against
        the memberships every time it is read. Without that, someone removed from a
        restaurant would keep landing on it and see a 403 on every request.
        """
        remembered = context.user.last_tenant_id
        if remembered is not None and self._can_see(context, remembered):
            return remembered
        if context.memberships:
            return context.memberships[0].tenant_id
        return None

    def _can_see(self, context: AuthContext, tenant_id: ObjectId) -> bool:
        """True when the caller still has a reason to be looking at this restaurant."""
        return context.is_platform_admin or context.role_at(tenant_id) is not None

    async def set_last_tenant(self, *, tenant_id: ObjectId, actor: AuthContext) -> Tenant:
        """Remember the restaurant the caller has switched to."""
        self.assert_member(actor, tenant_id)
        tenant = await self.get_tenant(tenant_id)
        await self._users.set_last_tenant(actor.user_id, tenant_id)
        return tenant

    # ------------------------------------------------------------------ platform roles

    async def list_users(self, *, limit: int = 100) -> list[User]:
        """Every registered person, newest first (admin only)."""
        return await self._users.find(limit=limit, sort=[("created_at", -1)])

    async def get_user(self, user_id: ObjectId) -> User:
        """Return one user or raise :class:`NotFoundError`."""
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def change_platform_role(
        self, *, user_id: ObjectId, role: PlatformRole, actor: AuthContext
    ) -> User:
        """Promote or demote a person on the platform (admin only).

        Self-demotion is refused, and so is demoting the last admin: either would leave
        nobody able to call this endpoint again.
        """
        target = await self.get_user(user_id)
        if target.platform_role is role:
            return target
        if user_id == actor.user_id:
            raise PermissionDeniedError("You cannot change your own platform role")
        # Unreachable through the HTTP API today (demoting the only admin means demoting
        # yourself, which the check above already refuses); it is here so a worker or a CLI
        # calling this service cannot leave the platform with no admin either.
        if target.platform_role is PlatformRole.ADMIN and await self._users.count_admins() <= 1:
            raise ConflictError("The last platform admin cannot be demoted")
        updated = await self._users.update_by_id(user_id, {"platform_role": role})
        if updated is None:
            raise NotFoundError("User not found")
        logger.info(
            "platform role changed: user=%s role=%s by=%s", target.email, role, actor.user.email
        )
        return updated

    # ------------------------------------------------------------------ memberships

    def assert_can_manage_tenant(self, context: AuthContext, tenant_id: ObjectId) -> None:
        """Allow a platform admin or the tenant's owner; refuse everyone else.

        Staff can read their tenant but never change who else belongs to it.
        """
        if context.is_platform_admin:
            return
        if context.role_at(tenant_id) is TenantRole.OWNER:
            return
        raise PermissionDeniedError("Only an owner of this restaurant can manage its team")

    def assert_member(self, context: AuthContext, tenant_id: ObjectId) -> None:
        """Allow a platform admin or any member of the tenant."""
        if context.is_platform_admin or context.role_at(tenant_id) is not None:
            return
        raise PermissionDeniedError("You are not a member of this restaurant")

    async def list_members(self, tenant_id: ObjectId) -> list[tuple[Membership, User]]:
        """Members of a tenant paired with the person behind each membership."""
        memberships = await self._memberships.list_for_tenant(tenant_id)
        if not memberships:
            return []
        users = await self._users.find({"_id": {"$in": [m.user_id for m in memberships]}})
        by_id = {user.id: user for user in users}
        return [(m, by_id[m.user_id]) for m in memberships if m.user_id in by_id]

    async def change_member_role(
        self, *, tenant_id: ObjectId, user_id: ObjectId, role: TenantRole, actor: AuthContext
    ) -> Membership:
        """Change someone's role at a restaurant, keeping at least one owner."""
        membership = await self._memberships.get_for(tenant_id, user_id)
        if membership is None:
            raise NotFoundError("This person is not a member of the restaurant")
        if membership.role is role:
            return membership
        await self._assert_not_last_owner(membership, action="demoted")
        assert membership.id is not None
        updated = await self._memberships.update_by_id(membership.id, {"role": role})
        if updated is None:
            raise NotFoundError("This person is not a member of the restaurant")
        logger.info(
            "membership role changed: tenant=%s user=%s role=%s by=%s",
            tenant_id,
            user_id,
            role,
            actor.user.email,
        )
        return updated

    async def remove_member(
        self, *, tenant_id: ObjectId, user_id: ObjectId, actor: AuthContext
    ) -> None:
        """Remove someone from a restaurant, keeping at least one owner."""
        membership = await self._memberships.get_for(tenant_id, user_id)
        if membership is None:
            raise NotFoundError("This person is not a member of the restaurant")
        await self._assert_not_last_owner(membership, action="removed")
        await self._memberships.remove(tenant_id, user_id)
        # The removed person may have had this restaurant remembered; leaving it there would
        # send them back to one that now answers 403. Only this one is forgotten - any other
        # restaurant they still belong to stays their choice.
        await self._users.clear_last_tenant(user_id, tenant_id)
        logger.info("member removed: tenant=%s user=%s by=%s", tenant_id, user_id, actor.user.email)

    async def _assert_not_last_owner(self, membership: Membership, *, action: str) -> None:
        """Refuse a change that would leave a tenant with no owner at all."""
        if membership.role is not TenantRole.OWNER:
            return
        if await self._memberships.count_owners(membership.tenant_id) <= 1:
            raise ConflictError(f"The last owner of a restaurant cannot be {action}")

    # ------------------------------------------------------------------ invites

    async def invite_member(
        self, *, tenant_id: ObjectId, email: str, role: TenantRole, actor: AuthContext
    ) -> tuple[Invite, str]:
        """Invite ``email`` to join a restaurant; returns the invite and its one-time token.

        The token is the only time the plaintext exists - the invite stores a digest. It is
        returned to the caller so the management UI (and, later, an email) can build the
        link; the membership itself is created when the invited person signs in with Google
        and proves that address.
        """
        await self.get_tenant(tenant_id)
        normalised = email.strip().lower()
        existing_user = await self._users.get_by_email(normalised)
        if existing_user is not None:
            assert existing_user.id is not None
            if await self._memberships.get_for(tenant_id, existing_user.id) is not None:
                raise ConflictError("That person is already a member of this restaurant")
        await self._invites.delete_lapsed(tenant_id, normalised)
        token = generate_token()
        invite = Invite(
            tenant_id=tenant_id,
            email=normalised,
            role=role,
            token_hash=hash_token(token),
            invited_by=actor.user_id,
            expires_at=utcnow() + self._settings.invite_ttl,
        )
        try:
            invite.id = await self._invites.insert(invite)
        except DuplicateKeyError as exc:
            raise ConflictError("An invite for that address is already pending") from exc
        logger.info("invite created: tenant=%s role=%s by=%s", tenant_id, role, actor.user.email)
        return invite, token

    async def list_invites(self, tenant_id: ObjectId, *, pending_only: bool = True) -> list[Invite]:
        """Invites issued by a tenant."""
        return await self._invites.list_for_tenant(tenant_id, pending_only=pending_only)

    async def revoke_invite(self, *, tenant_id: ObjectId, invite_id: ObjectId) -> None:
        """Withdraw a pending invite."""
        invite = await self._invites.get(invite_id)
        if invite is None or invite.tenant_id != tenant_id:
            raise NotFoundError("Invite not found")
        if invite.accepted_at is not None:
            raise ConflictError("That invite has already been accepted")
        await self._invites.delete(invite_id)
        logger.info("invite revoked: tenant=%s invite=%s", tenant_id, invite_id)


def _first_message(error: ValidationError) -> str:
    """The first validator message from a :class:`ValidationError`, without the boilerplate.

    Pydantic prefixes a custom ``ValueError`` with "Value error, "; the rest is the sentence
    the model author wrote for exactly this moment, so it is shown to the owner verbatim.
    """
    for item in error.errors():
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            field = ".".join(str(part) for part in item.get("loc", ()) if not isinstance(part, int))
            return f"{field}: {message}" if field else message
    return "That restaurant could not be saved"
