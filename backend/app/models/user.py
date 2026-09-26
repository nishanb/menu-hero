"""Global user identity and its repository.

A user is a *person*, not a person-at-a-restaurant: identity is keyed on the Google
subject and the verified email, and membership of a tenant is a separate document
(:mod:`app.models.membership`). That split is what lets someone sign in before they belong
to any restaurant - the "by default you are a `user`" rule of the onboarding flow - and it
lets one person be the owner of one tenant and staff at another.

There is deliberately no ``restaurants_managed`` array here. ``memberships`` already *is*
the list of restaurants a person manages, with the role attached; a copy on the user would
be a second source of truth that drifts the first time a membership is revoked. The one
tenant reference the user document does carry is :attr:`User.last_tenant_id`, which is a UI
preference ("the restaurant I was last looking at"), never an authorisation fact - it is
re-checked against the memberships on every read.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from pydantic import EmailStr, Field, field_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.roles import PlatformRole


def utcnow() -> datetime:
    """Timezone-aware "now" (the driver is opened with ``tz_aware=True``)."""
    return datetime.now(UTC)


class User(MongoDocument):
    """One person who has signed in with Google."""

    email: EmailStr
    google_sub: str = Field(description="Google's stable subject identifier for the account.")
    name: str = ""
    picture: str = ""
    platform_role: PlatformRole = PlatformRole.USER
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None
    last_tenant_id: PyObjectId | None = Field(
        default=None,
        description=(
            "The restaurant this person was last working on. A preference, not a grant: it "
            "is only honoured while a membership for it still exists."
        ),
    )

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        """Store emails lower-cased so lookups and invite matching are case-insensitive."""
        return value.strip().lower() if isinstance(value, str) else value


class UserRepository(MongoRepository[User]):
    """``users`` - unique on ``google_sub`` and on ``email``."""

    collection_name = "users"
    document_type = User

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel([("google_sub", ASCENDING)], name="uq_google_sub", unique=True),
                IndexModel([("email", ASCENDING)], name="uq_email", unique=True),
            ]
        )

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        """Look a user up by Google subject."""
        return await self.find_one({"google_sub": google_sub})

    async def get_by_email(self, email: str) -> User | None:
        """Look a user up by (lower-cased) email."""
        return await self.find_one({"email": email.strip().lower()})

    async def count_admins(self) -> int:
        """How many active platform admins exist (guards the last-admin rule)."""
        return await self.count({"platform_role": PlatformRole.ADMIN, "is_active": True})

    async def set_last_tenant(self, user_id: ObjectId, tenant_id: ObjectId | None) -> None:
        """Remember (or forget) the restaurant this person was last working on."""
        await self.collection.update_one({"_id": user_id}, {"$set": {"last_tenant_id": tenant_id}})

    async def clear_last_tenant(self, user_id: ObjectId, tenant_id: ObjectId) -> bool:
        """Forget ``tenant_id`` for one person, but only if it is what they had remembered.

        Called when they stop being a member of it: without this they keep landing on a
        restaurant that now answers 403. The ``last_tenant_id`` in the filter is the point -
        someone who belongs to three restaurants and is removed from one must not lose the
        other two as their remembered choice.
        """
        result = await self.collection.update_one(
            {"_id": user_id, "last_tenant_id": tenant_id}, {"$set": {"last_tenant_id": None}}
        )
        return result.modified_count > 0
