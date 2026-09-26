"""Authentication and authorisation dependencies.

The building blocks the routes compose:

* :data:`AuthServiceDep` / :data:`ManagementServiceDep` / :data:`CategoryServiceDep` /
  :data:`FloorPlanServiceDep` / :data:`MenuServiceDep` / :data:`GoogleBusinessServiceDep` -
  the use-case layers, built per request from the database handle so they are trivially
  overridable in tests.
* :data:`CurrentUser` - the signed-in :class:`~app.services.auth_service.AuthContext`,
  resolved from the session cookie; answers 401 when there is none.
* :data:`PlatformAdmin` - the same, restricted to ``platform_role == admin``.
* :data:`OptionalUser` - ``None`` instead of a 401, for endpoints that render differently
  when signed out.

Roles are read from the database on every request (the cookie only identifies a session),
so a role change through the management API applies to the caller's very next request.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.dependencies.database import Db
from app.dependencies.settings import SettingsDep
from app.services.auth_service import AuthContext, AuthService
from app.services.category_service import CategoryService
from app.services.floor_plan_service import FloorPlanService
from app.services.google_business import GoogleBusinessClient, GoogleBusinessProvider
from app.services.google_business_service import GoogleBusinessService
from app.services.google_oauth import GoogleIdentityProvider, GoogleOAuthClient
from app.services.image_store import DatabaseImageStore, ImageStore
from app.services.management_service import ManagementService
from app.services.menu_service import MenuService
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)

UNAUTHENTICATED_DETAIL = "Not signed in"
FORBIDDEN_DETAIL = "This action requires the platform admin role"


def get_google_identity_provider(settings: SettingsDep) -> GoogleIdentityProvider:
    """Return the Google client. Tests override this dependency with a double."""
    return GoogleOAuthClient(settings)


GoogleProviderDep = Annotated[GoogleIdentityProvider, Depends(get_google_identity_provider)]


def get_auth_service(
    db: Db, settings: SettingsDep, identity_provider: GoogleProviderDep
) -> AuthService:
    """Build the :class:`AuthService` for this request."""
    return AuthService(db, settings=settings, identity_provider=identity_provider)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
"""Route parameter annotation: ``auth: AuthServiceDep``."""


def get_management_service(db: Db, settings: SettingsDep) -> ManagementService:
    """Build the :class:`ManagementService` for this request."""
    return ManagementService(db, settings=settings)


ManagementServiceDep = Annotated[ManagementService, Depends(get_management_service)]
"""Route parameter annotation: ``management: ManagementServiceDep``."""


def get_category_service(db: Db) -> CategoryService:
    """Build the :class:`CategoryService` for this request."""
    return CategoryService(db)


CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
"""Route parameter annotation: ``categories: CategoryServiceDep``."""


def get_floor_plan_service(db: Db) -> FloorPlanService:
    """Build the :class:`FloorPlanService` for this request."""
    return FloorPlanService(db)


FloorPlanServiceDep = Annotated[FloorPlanService, Depends(get_floor_plan_service)]
"""Route parameter annotation: ``floor_plans: FloorPlanServiceDep``."""


def get_image_store(db: Db, settings: SettingsDep) -> ImageStore:
    """Where menu pictures are put.

    The one dependency to swap when a CDN arrives - see
    :mod:`app.services.image_store` for why nothing else has to change.
    """
    return DatabaseImageStore(db, settings=settings)


ImageStoreDep = Annotated[ImageStore, Depends(get_image_store)]
"""Route parameter annotation: ``images: ImageStoreDep``."""


def get_menu_service(db: Db, images: ImageStoreDep) -> MenuService:
    """Build the :class:`MenuService` for this request."""
    return MenuService(db, images=images)


MenuServiceDep = Annotated[MenuService, Depends(get_menu_service)]
"""Route parameter annotation: ``menu: MenuServiceDep``."""


def get_order_service(db: Db) -> OrderService:
    """Build the :class:`OrderService` for this request - the single writer for orders."""
    return OrderService(db)


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
"""Route parameter annotation: ``orders: OrderServiceDep``."""


def get_google_business_provider(settings: SettingsDep) -> GoogleBusinessProvider:
    """Return the Business Profile client. Tests override this dependency with a double."""
    return GoogleBusinessClient(settings)


GoogleBusinessProviderDep = Annotated[GoogleBusinessProvider, Depends(get_google_business_provider)]


def get_google_business_service(
    db: Db,
    settings: SettingsDep,
    provider: GoogleBusinessProviderDep,
    management: ManagementServiceDep,
) -> GoogleBusinessService:
    """Build the :class:`GoogleBusinessService` for this request."""
    return GoogleBusinessService(db, settings=settings, provider=provider, management=management)


GoogleBusinessServiceDep = Annotated[GoogleBusinessService, Depends(get_google_business_service)]
"""Route parameter annotation: ``google: GoogleBusinessServiceDep``."""


async def get_optional_auth_context(
    request: Request, auth: AuthServiceDep, settings: SettingsDep
) -> AuthContext | None:
    """Resolve the session cookie, or ``None`` when it is absent, unknown or expired."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return await auth.resolve_session(token)


OptionalUser = Annotated[AuthContext | None, Depends(get_optional_auth_context)]
"""Route parameter annotation: ``context: OptionalUser``."""


async def get_auth_context(context: OptionalUser) -> AuthContext:
    """Require a signed-in caller; 401 otherwise."""
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=UNAUTHENTICATED_DETAIL)
    return context


CurrentUser = Annotated[AuthContext, Depends(get_auth_context)]
"""Route parameter annotation: ``context: CurrentUser``."""


async def require_platform_admin(context: CurrentUser) -> AuthContext:
    """Require the platform admin role; 403 for anyone else."""
    if not context.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL)
    return context


PlatformAdmin = Annotated[AuthContext, Depends(require_platform_admin)]
"""Route parameter annotation: ``admin: PlatformAdmin``."""
