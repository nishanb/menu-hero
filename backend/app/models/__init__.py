"""MongoDB document models and repositories.

Shared building blocks (:mod:`app.models.base`) plus the collections the management app
needs: ``users`` (global identity), ``tenants``, ``memberships`` (who holds which role
where), ``sessions``, ``invites``, ``google_connections``, ``tables``, ``floor_plans`` and
``categories`` and ``menu_items``.
"""

from app.models.base import MongoDocument, MongoRepository, PyObjectId
from app.models.category import Category, CategoryRepository, CategoryStatus
from app.models.floor_plan import (
    ElementKind,
    ElementShape,
    FloorPlan,
    FloorPlanDraft,
    FloorPlanElement,
    FloorPlanRepository,
)
from app.models.google_connection import GoogleConnection, GoogleConnectionRepository
from app.models.invite import Invite, InviteRepository
from app.models.membership import Membership, MembershipRepository
from app.models.menu_item import AddonGroup, MenuItem, MenuItemRepository, Variation
from app.models.order import (
    Kot,
    KotRepository,
    Order,
    OrderKind,
    OrderLine,
    OrderRepository,
    OrderStatus,
)
from app.models.roles import (
    PORTAL_PATHS,
    PlatformRole,
    Role,
    TenantRole,
    effective_role,
    portal_path,
)
from app.models.session import Session, SessionRepository
from app.models.table import Table, TableRepository
from app.models.tenant import (
    SUGGESTED_DIET_OPTIONS,
    SUGGESTED_SERVICES,
    SlugAllocator,
    Tenant,
    TenantRepository,
    slugify,
)
from app.models.user import User, UserRepository, utcnow

__all__ = [
    "PORTAL_PATHS",
    "SUGGESTED_DIET_OPTIONS",
    "SUGGESTED_SERVICES",
    "Category",
    "CategoryRepository",
    "CategoryStatus",
    "ElementKind",
    "ElementShape",
    "FloorPlan",
    "FloorPlanDraft",
    "FloorPlanElement",
    "FloorPlanRepository",
    "GoogleConnection",
    "GoogleConnectionRepository",
    "Invite",
    "InviteRepository",
    "AddonGroup",
    "Membership",
    "MembershipRepository",
    "Kot",
    "KotRepository",
    "MenuItem",
    "MenuItemRepository",
    "MongoDocument",
    "MongoRepository",
    "Order",
    "OrderKind",
    "OrderLine",
    "OrderRepository",
    "OrderStatus",
    "PlatformRole",
    "PyObjectId",
    "Role",
    "Session",
    "SessionRepository",
    "SlugAllocator",
    "Table",
    "TableRepository",
    "Tenant",
    "TenantRepository",
    "TenantRole",
    "User",
    "UserRepository",
    "Variation",
    "effective_role",
    "portal_path",
    "slugify",
    "utcnow",
]
