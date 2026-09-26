"""A person's authorisation to read their Google Business Profile on their behalf.

Kept in its own collection rather than on ``users`` for two reasons: it holds a live
credential, so it should be readable and revocable on its own; and it is optional - most
people who sign in never grant it, and a null field on every user document would suggest
otherwise.

The refresh token is encrypted with :class:`~app.core.crypto.TokenCipher`, never returned
by any endpoint, and deleted outright when the person disconnects.
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow


class GoogleConnection(MongoDocument):
    """One person's Google Business Profile authorisation."""

    user_id: PyObjectId
    refresh_token_encrypted: str = Field(
        description="Fernet ciphertext of the refresh token. Never leaves the server."
    )
    scopes: list[str] = Field(default_factory=list, description="Scopes Google actually granted.")
    google_email: str = Field(default="", description="Which Google account was connected.")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None


class GoogleConnectionRepository(MongoRepository[GoogleConnection]):
    """``google_connections`` - at most one per person."""

    collection_name = "google_connections"
    document_type = GoogleConnection

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [IndexModel([("user_id", ASCENDING)], name="uq_user", unique=True)]
        )

    async def get_for_user(self, user_id: ObjectId) -> GoogleConnection | None:
        """The person's connection, or ``None`` when they have not granted access."""
        return await self.find_one({"user_id": user_id})

    async def upsert(self, connection: GoogleConnection) -> None:
        """Store or replace the person's connection.

        An upsert rather than an insert: re-running consent is the normal way to repair a
        revoked or expired grant, and it must not collide with ``uq_user``.
        """
        body = connection.to_mongo()
        body.pop("created_at", None)
        await self.collection.update_one(
            {"user_id": connection.user_id},
            {"$set": body, "$setOnInsert": {"created_at": connection.created_at}},
            upsert=True,
        )

    async def touch(self, user_id: ObjectId) -> None:
        """Record that the connection was used, so a stale grant is visible to an operator."""
        await self.collection.update_one({"user_id": user_id}, {"$set": {"last_used_at": utcnow()}})

    async def remove_for_user(self, user_id: ObjectId) -> bool:
        """Forget the person's connection; ``True`` when one was removed."""
        result = await self.collection.delete_one({"user_id": user_id})
        return result.deleted_count > 0
