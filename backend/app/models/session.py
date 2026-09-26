"""Server-side sessions for the management app.

The cookie carries an opaque token, not a signed claim set. Two consequences the flow
depends on: a session can be revoked at logout, and - because only ``user_id`` is stored -
a role change made through the management API is in force on the *next* request rather
than whenever a month-long token happens to expire.
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow


class Session(MongoDocument):
    """One signed-in browser."""

    user_id: PyObjectId
    token_hash: str = Field(description="SHA-256 of the cookie value; the token is never stored.")
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    last_seen_at: datetime = Field(default_factory=utcnow)
    user_agent: str = ""


class SessionRepository(MongoRepository[Session]):
    """``sessions`` - unique on ``token_hash``, swept by a TTL index on ``expires_at``."""

    collection_name = "sessions"
    document_type = Session

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel([("token_hash", ASCENDING)], name="uq_token_hash", unique=True),
                # MongoDB's TTL monitor only sweeps once a minute, so lookups still compare
                # `expires_at` themselves; this index is the garbage collector, not the check.
                IndexModel(
                    [("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0
                ),
                IndexModel([("user_id", ASCENDING)], name="ix_user"),
            ]
        )

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        """Look a session up by the digest of its cookie value."""
        return await self.find_one({"token_hash": token_hash})

    async def touch(self, session_id: ObjectId) -> None:
        """Record activity on a session (diagnostics only; it does not extend the expiry)."""
        await self.collection.update_one({"_id": session_id}, {"$set": {"last_seen_at": utcnow()}})

    async def revoke_by_token_hash(self, token_hash: str) -> bool:
        """Delete one session; ``True`` when it existed."""
        result = await self.collection.delete_one({"token_hash": token_hash})
        return result.deleted_count > 0

    async def revoke_all_for_user(self, user_id: ObjectId) -> int:
        """Sign a person out of every browser (deactivation)."""
        return await self.delete_many({"user_id": user_id})
