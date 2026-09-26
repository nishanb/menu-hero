"""The four roles of the management app, and where each one lands after sign-in.

Roles live at two different scopes and are deliberately kept in separate enums:

* :class:`PlatformRole` is a property of the *person* (``users.platform_role``). Everyone
  who signs in with Google is a ``user``; ``admin`` is the operator role that runs the
  platform and is granted by another admin.
* :class:`TenantRole` is a property of a *membership* (``memberships.role``): the same
  person can be the ``owner`` of one restaurant and ``staff`` at another.

A person's effective role for portal routing is the strongest one they hold, in the order
of :data:`ROLE_PRECEDENCE`.
"""

from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    """Role carried by the user document itself."""

    ADMIN = "admin"
    USER = "user"


class TenantRole(StrEnum):
    """Role carried by a membership of one tenant."""

    OWNER = "owner"
    STAFF = "staff"


Role = PlatformRole | TenantRole
"""Either scope's role, as used for portal routing."""

ROLE_PRECEDENCE: tuple[Role, ...] = (
    PlatformRole.ADMIN,
    TenantRole.OWNER,
    TenantRole.STAFF,
    PlatformRole.USER,
)
"""Strongest first. :func:`effective_role` picks the first one the person holds."""

PORTAL_PATHS: dict[Role, str] = {
    PlatformRole.ADMIN: "/admin",
    TenantRole.OWNER: "/owner",
    TenantRole.STAFF: "/staff",
    PlatformRole.USER: "/app",
}
"""Frontend path each role is sent to after a successful sign-in."""


def effective_role(platform_role: PlatformRole, tenant_roles: set[TenantRole]) -> Role:
    """Return the strongest role held, given the platform role and every membership role."""
    held: set[Role] = {platform_role, *tenant_roles}
    return next(role for role in ROLE_PRECEDENCE if role in held)


def portal_path(role: Role) -> str:
    """Frontend path for ``role``."""
    return PORTAL_PATHS[role]
