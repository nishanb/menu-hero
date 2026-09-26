"""HTTP schemas of the authentication endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import PlatformRole, TenantRole, User
from app.models.base import PyObjectId


class UserOut(BaseModel):
    """A person, as the management app sees them."""

    model_config = ConfigDict(from_attributes=True)

    id: PyObjectId = Field(description="User id.")
    email: str
    name: str = ""
    picture: str = ""
    platform_role: PlatformRole
    is_active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        """Project a stored :class:`~app.models.user.User`."""
        return cls.model_validate(user, from_attributes=True)


class MembershipOut(BaseModel):
    """One restaurant the signed-in person belongs to, and the role they hold there."""

    tenant_id: PyObjectId
    tenant_slug: str = ""
    tenant_name: str = ""
    role: TenantRole


class MeResponse(BaseModel):
    """Body of ``GET /api/v1/auth/me`` - everything the SPA needs to render a shell."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user": {
                        "id": "665f1c2b9a1e4f0012ab34cd",
                        "email": "chef@example.com",
                        "name": "Chef",
                        "platform_role": "user",
                        "is_active": True,
                        "created_at": "2026-09-07T10:00:00Z",
                    },
                    "effective_role": "owner",
                    "portal_path": "/owner",
                    "memberships": [
                        {
                            "tenant_id": "665f1c2b9a1e4f0012ab34ce",
                            "tenant_slug": "spice-garden",
                            "tenant_name": "Spice Garden",
                            "role": "owner",
                        }
                    ],
                    "active_tenant_id": "665f1c2b9a1e4f0012ab34ce",
                }
            ]
        }
    )

    user: UserOut
    effective_role: str = Field(description="Strongest role held: admin, owner, staff or user.")
    portal_path: str = Field(description="Frontend path this person is routed to.")
    memberships: list[MembershipOut] = Field(default_factory=list)
    active_tenant_id: PyObjectId | None = Field(
        default=None,
        description=(
            "The restaurant to open on: the one this person last switched to while they "
            "still belong to it, otherwise the first they hold. Null when they belong to "
            "none, which is what sends them to onboarding."
        ),
    )


class LogoutResponse(BaseModel):
    """Body of ``POST /api/v1/auth/logout``."""

    signed_out: bool = True


class InviteAcceptRequest(BaseModel):
    """Body of ``POST /api/v1/auth/invites/accept`` (for an already signed-in person)."""

    token: str = Field(min_length=16, max_length=200, description="The invite token.")
