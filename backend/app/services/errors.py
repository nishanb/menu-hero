"""Domain errors of the management services and their HTTP status codes.

Services raise these instead of ``HTTPException`` so they stay usable from a worker or a
CLI; ``app.main`` registers one handler that turns them into the JSON error body the rest
of the API uses (``{"detail": ...}``).
"""

from __future__ import annotations

from http import HTTPStatus


class ManagementError(RuntimeError):
    """A management operation was refused. The message is safe to show the caller."""

    status_code: int = HTTPStatus.BAD_REQUEST


class ValidationFailedError(ManagementError):
    """A field was refused by the document model (bad logo, oversized property, ...).

    Distinct from FastAPI's own 422: the value reached the service through a path the
    request schema does not police - an imported Google Business location, or a merge of a
    patch onto a stored document - and the model's own message is what the owner should see.
    """

    status_code = HTTPStatus.BAD_REQUEST


class NotFoundError(ManagementError):
    """The tenant, user, membership or invite does not exist."""

    status_code = HTTPStatus.NOT_FOUND


class PermissionDeniedError(ManagementError):
    """The caller is signed in but not allowed to do this."""

    status_code = HTTPStatus.FORBIDDEN


class ConflictError(ManagementError):
    """The change collides with existing state (duplicate slug, already a member, ...)."""

    status_code = HTTPStatus.CONFLICT
