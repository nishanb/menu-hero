"""Serving a stored menu picture.

    GET /api/v1/images/{image_id}   (member of the restaurant the picture belongs to)

Exists because the bytes are in MongoDB for now. When a CDN takes over, items will carry its
URLs instead and this route serves only the pictures imported before the switch - see
:mod:`app.services.image_store`.

Gated on membership rather than public: there is no diner surface yet, and a menu picture
becomes public the day there is one, not before.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.dependencies.database import Db
from app.models import PyObjectId
from app.models.menu_image import MenuImageRepository
from app.services.errors import NotFoundError

router = APIRouter(prefix="/images")

CACHE_CONTROL = "private, max-age=86400, immutable"
"""Content-addressed, so a stored picture never changes under a given id."""

RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such picture"},
}


@router.get(
    "/{image_id}",
    responses=RESPONSES,
    response_class=Response,
    summary="One menu picture",
)
async def get_image(image_id: PyObjectId, db: Db) -> Response:
    """The image bytes, with the content type they were stored under.

    Public: the diner's menu shows these to anyone with the QR code, and a menu picture is
    the least secret thing a restaurant owns. The id is an ObjectId - unguessable enough for
    a photo of a dosa.
    """
    image = await MenuImageRepository(db).get(image_id)
    if image is None:
        raise NotFoundError("No such picture")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": CACHE_CONTROL},
    )
