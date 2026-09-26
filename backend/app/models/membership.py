"""Tenant membership: which person holds which role at which restaurant."""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.roles import TenantRole
from app.models.user import utcnow


class Membership(MongoDocument):
    """``user_id`` holds ``role`` at ``tenant_id``."""

    tenant_id: PyObjectId
    user_id: PyObjectId
    role: TenantRole
    invited_by: PyObjectId | None = None
    created_at: datetime = Field(default_factory=utcnow)


class MembershipRepository(MongoRepository[Membership]):
    """``memberships`` - one role per person per tenant."""

    collection_name = "memberships"
    document_type = Membership

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("user_id", ASCENDING)],
                    name="uq_tenant_user",
                    unique=True,
                ),
                IndexModel([("user_id", ASCENDING)], name="ix_user"),
            ]
        )

    async def list_for_user(self, user_id: ObjectId) -> list[Membership]:
        """Every membership the person holds (drives portal routing and tenant guards)."""
        return await self.find({"user_id": user_id})

    async def list_for_tenant(self, tenant_id: ObjectId) -> list[Membership]:
        """Every member of one tenant."""
        return await self.find({"tenant_id": tenant_id})

    async def get_for(self, tenant_id: ObjectId, user_id: ObjectId) -> Membership | None:
        """The membership of one person at one tenant, if any."""
        return await self.find_one({"tenant_id": tenant_id, "user_id": user_id})

    async def count_owners(self, tenant_id: ObjectId) -> int:
        """How many owners a tenant has (guards the last-owner rule)."""
        return await self.count({"tenant_id": tenant_id, "role": TenantRole.OWNER})

    async def remove(self, tenant_id: ObjectId, user_id: ObjectId) -> bool:
        """Drop one membership; ``True`` when something was removed."""
        result = await self.collection.delete_one({"tenant_id": tenant_id, "user_id": user_id})
        return result.deleted_count > 0
