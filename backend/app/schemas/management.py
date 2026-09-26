"""HTTP schemas of the restaurant, membership, invite and platform-role endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Invite, Membership, PlatformRole, Tenant, TenantRole, User
from app.models.base import PyObjectId
from app.models.tenant import MAX_EXTRAS, MAX_LOGO_LENGTH, MAX_OPTIONS, PosSettings
from app.schemas.auth import UserOut

RESTAURANT_EXAMPLE: dict[str, Any] = {
    "name": "Spice Garden",
    "description": "Coastal Karnataka home cooking, open since 1984.",
    "location_url": "https://maps.app.goo.gl/example",
    "services": ["dining", "delivery"],
    "diet_options": ["veg", "non-veg"],
    "extras": {"fssai_licence": "12345678901234", "gst_number": "29ABCDE1234F1Z5"},
}


class RestaurantProfile(BaseModel):
    """The editable half of a restaurant: everything onboarding and settings collect.

    Shared by create and update so the two can never drift. The document model
    (:class:`~app.models.tenant.Tenant`) is what actually validates the *contents* - the
    caps here exist so an oversized body is refused before it reaches the database.
    """

    description: str | None = Field(default=None, max_length=2000)
    location_url: str | None = Field(
        default=None, max_length=2000, description="Google Maps link; must be https://."
    )
    logo: str | None = Field(
        default=None,
        max_length=MAX_LOGO_LENGTH,
        description="Base64 PNG, JPEG or WEBP data URL, or an empty string to remove it.",
    )
    services: list[str] | None = Field(
        default=None,
        max_length=MAX_OPTIONS,
        description="How the restaurant trades: dining, delivery, and any others it adds.",
    )
    diet_options: list[str] | None = Field(
        default=None,
        max_length=MAX_OPTIONS,
        description="Diets catered for. Open-ended: veg and non-veg are suggestions, not a set.",
    )
    extras: dict[str, str] | None = Field(
        default=None,
        max_length=MAX_EXTRAS,
        description="Free-form properties such as an FSSAI licence or a GST number.",
    )

    def as_changes(self) -> dict[str, Any]:
        """The fields the caller actually sent, ready for the service layer.

        ``exclude_unset``, not ``exclude_none``: it is the difference between "leave the
        description alone" and "clear the description".
        """
        return self.model_dump(exclude_unset=True, exclude_none=True)


class TenantCreate(RestaurantProfile):
    """Body of ``POST /api/v1/tenants``.

    Any signed-in person may create a restaurant and becomes its owner. There is no
    ``slug``: the server derives a free one from the name, because onboarding asks for a
    restaurant, not a URL handle.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [RESTAURANT_EXAMPLE]})

    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr | None = Field(
        default=None,
        description=(
            "Platform admins only: hand the new restaurant to an existing user. Ignored "
            "for everyone else, who always own what they create."
        ),
    )


class TenantUpdate(RestaurantProfile):
    """Body of ``PATCH /api/v1/tenants/{tenant_id}``. Every field is optional."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"description": "Now open Sundays."}]}
    )

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    pos: PosSettings | None = Field(
        default=None, description="Which parts of the till run here; see PosSettings."
    )


class TenantOut(BaseModel):
    """One restaurant.

    ``logo`` is absent from every endpoint that returns more than one - a switcher with
    five restaurants must not download five embedded images - and present on
    ``GET /api/v1/tenants/{id}``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId
    slug: str
    name: str
    description: str = ""
    location_url: str = ""
    logo: str = ""
    services: list[str] = Field(default_factory=list)
    diet_options: list[str] = Field(default_factory=list)
    extras: dict[str, str] = Field(default_factory=dict)
    google_location: str | None = None
    pos: PosSettings = Field(default_factory=PosSettings)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_tenant(cls, tenant: Tenant) -> TenantOut:
        """Project a stored :class:`~app.models.tenant.Tenant`."""
        return cls.model_validate(tenant, from_attributes=True)


class TenantListResponse(BaseModel):
    """Body of ``GET /api/v1/tenants``."""

    tenants: list[TenantOut] = Field(default_factory=list)
    active_tenant_id: PyObjectId | None = Field(
        default=None,
        description=(
            "The restaurant to open on: the caller's last chosen one while they still "
            "belong to it, otherwise the first in the list."
        ),
    )


class RestaurantOptionsResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/options`` - what the onboarding form offers.

    Suggestions, not a closed set: both fields accept anything a restaurant types in.
    """

    services: list[str] = Field(default_factory=list)
    diet_options: list[str] = Field(default_factory=list)


class UserListResponse(BaseModel):
    """Body of ``GET /api/v1/users`` (admin only)."""

    users: list[UserOut] = Field(default_factory=list)


class PlatformRoleUpdate(BaseModel):
    """Body of ``PATCH /api/v1/users/{user_id}/role`` (admin only)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"role": "admin"}]})

    role: PlatformRole


class MemberOut(BaseModel):
    """One member of a restaurant."""

    user: UserOut
    role: TenantRole
    created_at: datetime

    @classmethod
    def from_membership(cls, membership: Membership, user: User) -> MemberOut:
        """Pair a membership with the person it belongs to."""
        return cls(
            user=UserOut.from_user(user), role=membership.role, created_at=membership.created_at
        )


class MemberListResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/{tenant_id}/members``."""

    members: list[MemberOut] = Field(default_factory=list)


class MemberRoleUpdate(BaseModel):
    """Body of ``PATCH /api/v1/tenants/{tenant_id}/members/{user_id}``."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"role": "staff"}]})

    role: TenantRole


class InviteCreate(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/invites``."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "server@example.com", "role": "staff"}]}
    )

    email: EmailStr
    role: TenantRole = TenantRole.STAFF


class InviteOut(BaseModel):
    """One invitation (never carries the token)."""

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId
    tenant_id: PyObjectId
    email: str
    role: TenantRole
    invited_by: PyObjectId
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None

    @classmethod
    def from_invite(cls, invite: Invite) -> InviteOut:
        """Project a stored :class:`~app.models.invite.Invite`."""
        return cls.model_validate(invite, from_attributes=True)


class InviteListResponse(BaseModel):
    """Body of ``GET /api/v1/tenants/{tenant_id}/invites``."""

    invites: list[InviteOut] = Field(default_factory=list)


class InviteCreatedResponse(BaseModel):
    """Body of ``POST /api/v1/tenants/{tenant_id}/invites``.

    The token is returned exactly once, here: only its digest is stored. Until invite email
    is wired up, this is how the operator gets the link to the invited person.
    """

    invite: InviteOut
    token: str = Field(description="One-time invite token; shown once and never again.")
    accept_url: str = Field(description="Ready-made link for the invited person.")
