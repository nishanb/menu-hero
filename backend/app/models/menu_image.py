"""Menu images, while there is no CDN to put them in.

An item's picture belongs on a CDN: it is large, immutable, and wanted by every diner at
once. There is no CDN wired up yet, so the bytes live here - one document per distinct image,
addressed by the SHA-256 of its content.

This collection is a **bridge, not a destination**. Nothing outside
:mod:`app.services.image_store` knows it exists, and an item stores only the URL its image is
served from, so pointing that at a real CDN later changes one file and no data.

Content-addressed on purpose: a POS export commonly repeats the same placeholder picture
across dozens of rows, and a bulk import should not store it dozens of times.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository, PyObjectId
from app.models.user import utcnow

ALLOWED_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
"""SVG is excluded on purpose: it is a document that can carry script, not a picture."""

MAX_IMAGE_BYTES = 2 * 1024 * 1024
"""2 MB of decoded image. Bigger than any menu photo needs to be, small enough to serve."""


class MenuImage(MongoDocument):
    """One stored picture."""

    tenant_id: PyObjectId
    digest: str = Field(max_length=64, description="SHA-256 of ``data``; the identity.")
    content_type: str = Field(max_length=64)
    size: int = Field(ge=0, le=MAX_IMAGE_BYTES)
    data: bytes
    created_at: datetime = Field(default_factory=utcnow)


class MenuImageRepository(MongoRepository[MenuImage]):
    """``menu_images`` - unique on (``tenant_id``, ``digest``)."""

    collection_name = "menu_images"
    document_type = MenuImage

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel(
                    [("tenant_id", ASCENDING), ("digest", ASCENDING)],
                    name="uq_tenant_digest",
                    unique=True,
                )
            ]
        )

    async def get_by_digest(self, tenant_id: PyObjectId, digest: str) -> MenuImage | None:
        """The stored copy of this exact content, if there is one."""
        return await self.find_one({"tenant_id": tenant_id, "digest": digest})


__all__ = ["ALLOWED_TYPES", "MAX_IMAGE_BYTES", "MenuImage", "MenuImageRepository"]
