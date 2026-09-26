"""Invitations to join a tenant as owner or staff.

There are no passwords, so an invite is not a credential to sign in with - it is a
*pending membership* keyed on an email address. It is consumed when the invited person
first signs in with Google and their verified email matches, or when someone already
signed in posts the invite token. Either way the membership is created by the server, so
holding the link never grants a role for an email the holder cannot prove.
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from pydantic import EmailStr, Field, field_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.roles import TenantRole
from app.models.user import utcnow


class Invite(MongoDocument):
    """One outstanding invitation."""

    tenant_id: PyObjectId
    email: EmailStr
    role: TenantRole
    token_hash: str = Field(description="SHA-256 of the invite token; the token is never stored.")
    invited_by: PyObjectId
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    accepted_at: datetime | None = None
    accepted_by: PyObjectId | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def is_pending(self) -> bool:
        """True while the invite is neither accepted nor expired."""
        return self.accepted_at is None and self.expires_at > utcnow()


class InviteRepository(MongoRepository[Invite]):
    """``invites`` - unique on ``token_hash``; at most one *pending* invite per email+tenant."""

    collection_name = "invites"
    document_type = Invite

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel([("token_hash", ASCENDING)], name="uq_token_hash", unique=True),
                IndexModel(
                    [("tenant_id", ASCENDING), ("email", ASCENDING)],
                    name="uq_pending_tenant_email",
                    unique=True,
                    partialFilterExpression={"accepted_at": None},
                ),
                IndexModel([("email", ASCENDING)], name="ix_email"),
            ]
        )

    async def get_by_token_hash(self, token_hash: str) -> Invite | None:
        """Look an invite up by the digest of its token."""
        return await self.find_one({"token_hash": token_hash})

    async def list_pending_for_email(self, email: str) -> list[Invite]:
        """Every unaccepted, unexpired invite addressed to ``email``."""
        return await self.find(
            {"email": email.strip().lower(), "accepted_at": None, "expires_at": {"$gt": utcnow()}}
        )

    async def list_for_tenant(
        self, tenant_id: ObjectId, *, pending_only: bool = True
    ) -> list[Invite]:
        """Invites issued by one tenant, pending ones by default."""
        query: dict[str, object] = {"tenant_id": tenant_id}
        if pending_only:
            query |= {"accepted_at": None, "expires_at": {"$gt": utcnow()}}
        return await self.find(query, sort=[("created_at", -1)])

    async def delete_lapsed(self, tenant_id: ObjectId, email: str) -> int:
        """Drop an unaccepted invite that has expired.

        ``uq_pending_tenant_email`` is partial on ``accepted_at: None``, which expiry does
        not change - without this, a lapsed invite would block re-inviting the same address
        until someone revoked it by hand.
        """
        return await self.delete_many(
            {
                "tenant_id": tenant_id,
                "email": email.strip().lower(),
                "accepted_at": None,
                "expires_at": {"$lte": utcnow()},
            }
        )

    async def mark_accepted(self, invite_id: ObjectId, user_id: ObjectId) -> None:
        """Close an invite out once its membership exists."""
        await self.collection.update_one(
            {"_id": invite_id}, {"$set": {"accepted_at": utcnow(), "accepted_by": user_id}}
        )
