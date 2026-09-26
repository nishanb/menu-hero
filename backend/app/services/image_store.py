"""Where a menu picture is put, and the seam that lets that change.

Today the bytes go in MongoDB (:mod:`app.models.menu_image`) and are served back from
``/api/v1/images/{id}``. That is a bridge: an item's picture is large, immutable and wanted
by every diner at once, which is a CDN's job and not a database's.

The seam is :class:`ImageStore`. An item stores only ``image_url`` - never the bytes, never a
base64 blob - so putting a real CDN behind this is one new implementation of the protocol and
a dependency swap in ``app.dependencies.auth``. No stored document changes, and no caller
outside this module learns anything about where the bytes went.

Base64 arrives here because a bulk import carries pictures inline in a CSV cell. It is
decoded once, on the way in, and never stored in that form: a data URL on 400 items is
megabytes of document nobody can cache.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
from typing import Protocol

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.database import MongoDatabase
from app.models.menu_image import ALLOWED_TYPES, MAX_IMAGE_BYTES, MenuImage, MenuImageRepository

logger = logging.getLogger(__name__)

DATA_URL_PATTERN = re.compile(
    r"^data:(?P<type>image/[a-z0-9.+-]+);base64,(?P<body>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
"""``data:image/png;base64,iVBOR...``. Anything else is not a picture we will decode."""

IMAGE_PATH = "/v1/images"
"""Path of the serving route, under the API prefix. A CDN store returns its own origin."""


class ImageError(ValueError):
    """The cell was meant to be a picture and was not. The message is safe to show."""


class ImageStore(Protocol):
    """Somewhere to put an image and get back a URL for it."""

    async def store(self, *, tenant_id: ObjectId, data: bytes, content_type: str) -> str:
        """Store the bytes and return the URL they are served at."""
        ...

    async def store_data_url(self, *, tenant_id: ObjectId, data_url: str) -> str:
        """Decode a ``data:image/...;base64,...`` value and return the URL it is served at."""
        ...


class DatabaseImageStore:
    """Keeps the bytes in MongoDB, content-addressed so a repeated picture is stored once.

    A POS export commonly repeats one placeholder across dozens of rows; storing it dozens of
    times would be the difference between a 2 MB import and a 100 MB one.
    """

    def __init__(self, database: MongoDatabase, *, settings: Settings) -> None:
        self._images = MenuImageRepository(database)
        # Built from the configured prefix rather than hard-coded: the URL is *stored* on
        # every item, so getting it wrong is not a 404 today, it is 400 bad rows forever.
        self._prefix = f"{settings.api_prefix.rstrip('/')}{IMAGE_PATH}"

    def _url(self, image_id: object) -> str:
        return f"{self._prefix}/{image_id}"

    async def store_data_url(self, *, tenant_id: ObjectId, data_url: str) -> str:
        content_type, payload = decode_data_url(data_url)
        return await self.store(tenant_id=tenant_id, data=payload, content_type=content_type)

    async def store(self, *, tenant_id: ObjectId, data: bytes, content_type: str) -> str:
        payload = check_image(data, content_type)
        digest = hashlib.sha256(payload).hexdigest()

        existing = await self._images.get_by_digest(tenant_id, digest)
        if existing is not None and existing.id is not None:
            return self._url(existing.id)

        image = MenuImage(
            tenant_id=tenant_id,
            digest=digest,
            content_type=content_type,
            size=len(payload),
            data=payload,
        )
        try:
            image.id = await self._images.insert(image)
        except DuplicateKeyError:
            # Two rows of the same import carrying the same picture, racing. Whichever landed
            # first is the one we point at.
            stored = await self._images.get_by_digest(tenant_id, digest)
            if stored is None or stored.id is None:
                raise ImageError("That image could not be stored.") from None
            return self._url(stored.id)
        return self._url(image.id)


def check_image(data: bytes, content_type: str) -> bytes:
    """The bytes, if they are an image of a type and size we will keep.

    The one gate every path goes through - the import's base64 and the form's upload alike -
    so a rule added here cannot be walked around by picking the other door.
    """
    kind = content_type.split(";")[0].strip().lower()
    if kind not in ALLOWED_TYPES:
        raise ImageError(f"{kind or 'that'} is not an image type we store")
    if not data:
        raise ImageError("the image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"the image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return data


def data_url_type(value: str) -> str | None:
    """The image type a data URL declares, if it declares one we would store.

    Checked without decoding, so the preview can tell the truth about which pictures will
    survive the commit without doing the commit's work. An SVG is refused here, not later:
    it is a document that can carry script, not a picture.
    """
    match = DATA_URL_PATTERN.match(value.strip())
    if match is None:
        return None
    content_type = match.group("type").lower()
    return content_type if content_type in ALLOWED_TYPES else None


def decode_data_url(value: str) -> tuple[str, bytes]:
    """``data:image/png;base64,...`` -> ``("image/png", b"...")``.

    Raises :class:`ImageError` with a sentence worth showing, never a stack trace: this runs
    once per row of a bulk import, and a bad cell must cost the cell.
    """
    match = DATA_URL_PATTERN.match(value.strip())
    if match is None:
        raise ImageError("not a base64 image")
    content_type = match.group("type").lower()
    if content_type not in ALLOWED_TYPES:
        raise ImageError(f"{content_type} images are not accepted")
    try:
        payload = base64.b64decode(re.sub(r"\s+", "", match.group("body")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageError("the base64 could not be decoded") from exc
    return content_type, check_image(payload, content_type)


__all__ = [
    "DATA_URL_PATTERN",
    "IMAGE_PATH",
    "DatabaseImageStore",
    "ImageError",
    "ImageStore",
    "check_image",
    "data_url_type",
    "decode_data_url",
]
