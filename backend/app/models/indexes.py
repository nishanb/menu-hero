"""Index creation for every collection the application owns.

``create_indexes`` is idempotent in MongoDB, so this runs on every start-up. It is called
from the application lifespan only when ``DATABASE_URL`` is set - a deployment without a
database still boots, exactly as the rest of ``app.core.database`` assumes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.database import MongoDatabase
from app.models.base import MongoRepository
from app.models.category import CategoryRepository
from app.models.floor_plan import FloorPlanRepository
from app.models.google_connection import GoogleConnectionRepository
from app.models.invite import InviteRepository
from app.models.membership import MembershipRepository
from app.models.menu_image import MenuImageRepository
from app.models.menu_item import MenuItemRepository
from app.models.order import KotRepository, OrderRepository
from app.models.session import SessionRepository
from app.models.table import TableRepository
from app.models.tenant import TenantRepository
from app.models.user import UserRepository

logger = logging.getLogger(__name__)

REPOSITORIES: tuple[type[MongoRepository[Any]], ...] = (
    UserRepository,
    TenantRepository,
    MembershipRepository,
    SessionRepository,
    InviteRepository,
    GoogleConnectionRepository,
    TableRepository,
    FloorPlanRepository,
    CategoryRepository,
    MenuItemRepository,
    MenuImageRepository,
    OrderRepository,
    KotRepository,
)
"""Every repository whose indexes are created at start-up."""


async def ensure_indexes(database: MongoDatabase) -> None:
    """Create the indexes of every registered collection."""
    for repository_type in REPOSITORIES:
        await repository_type(database).ensure_indexes()
    logger.info("mongodb indexes ensured for %d collections", len(REPOSITORIES))
