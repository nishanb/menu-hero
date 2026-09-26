"""Google sign-in, sessions and invite acceptance.

    GET  /api/v1/auth/google           -> 307 to Google's consent screen
    GET  /api/v1/auth/google/callback  -> session cookie + 302 to the caller's portal
    GET  /api/v1/auth/me               -> who is signed in, and what they may do
    POST /api/v1/auth/logout           -> revoke the session, clear the cookie
    POST /api/v1/auth/invites/accept   -> join a restaurant with an invite token

The two redirect endpoints are browser navigations, so every failure ends as a redirect to
the frontend's login page with an ``error`` code rather than as a JSON body the user would
see as raw text.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import Settings
from app.dependencies.auth import AuthServiceDep, CurrentUser, ManagementServiceDep
from app.dependencies.settings import SettingsDep
from app.schemas.auth import (
    InviteAcceptRequest,
    LogoutResponse,
    MembershipOut,
    MeResponse,
    UserOut,
)
from app.services.auth_service import AuthContext, AuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

STATE_COOKIE_NAME = "mh_oauth_state"
STATE_COOKIE_MAX_AGE_SECONDS = 600
"""Ten minutes is long enough to sign in and short enough to be a poor replay target."""

LOGIN_PATH = "/login"
"""Frontend route a failed sign-in is sent back to, with ``?error=<code>``."""


def cookie_kwargs(settings: Settings) -> dict[str, object]:
    """Cookie attributes shared by every cookie this application sets.

    Also used by the Google Business connect flow, which sets a state cookie of its own.

    ``SameSite=Lax`` rather than ``Strict``: the callback arrives as a top-level navigation
    from Google, and a Strict cookie would not be sent on it - the sign-in would loop.
    ``Secure`` only in production so http://127.0.0.1 development keeps working.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.is_production,
        "path": "/",
    }


def set_session_cookie(
    response: Response, settings: Settings, *, token: str, expires_at: datetime
) -> None:
    """Attach the session cookie, expiring with the session document itself."""
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(settings.session_ttl.total_seconds()),
        expires=expires_at,
        **cookie_kwargs(settings),  # type: ignore[arg-type]
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Remove the session cookie (attributes must match the ones it was set with)."""
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def _login_error_redirect(settings: Settings, code: str) -> RedirectResponse:
    """Send the browser back to the frontend login page with a machine-readable reason."""
    query = urlencode({"error": code})
    response = RedirectResponse(
        f"{settings.frontend_base_url}{LOGIN_PATH}?{query}", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    return response


@router.get(
    "/google",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses={
        307: {"description": "Redirect to Google's consent screen"},
        503: {"description": "Google sign-in is not configured on this deployment"},
    },
    summary="Start Google sign-in",
)
async def google_login(
    auth: AuthServiceDep,
    settings: SettingsDep,
    next: Annotated[
        str | None,
        Query(max_length=512, description="Same-origin path to return to; ignored otherwise."),
    ] = None,
) -> RedirectResponse:
    """Redirect to Google, remembering a CSRF state (and where to come back to) in a cookie."""
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    authorization_url, state = auth.start_login(next)
    response = RedirectResponse(authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        STATE_COOKIE_NAME,
        state.encode(),
        max_age=STATE_COOKIE_MAX_AGE_SECONDS,
        **cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return response


@router.get(
    "/google/callback",
    status_code=status.HTTP_302_FOUND,
    responses={302: {"description": "Signed in (session cookie set) or back to /login?error=..."}},
    summary="Google sign-in callback",
)
async def google_callback(
    request: Request,
    auth: AuthServiceDep,
    settings: SettingsDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """Finish the round trip: exchange the code, open a session, land on the right portal."""
    if error is not None:
        logger.info("google sign-in cancelled or refused: %s", error)
        return _login_error_redirect(settings, "google_declined")
    if not code or not state:
        return _login_error_redirect(settings, "missing_code")
    try:
        result = await auth.complete_login(
            code=code,
            state=state,
            state_cookie=request.cookies.get(STATE_COOKIE_NAME),
            user_agent=request.headers.get("user-agent", ""),
        )
    except AuthError as exc:
        logger.info("sign-in failed: %s", exc.code)
        return _login_error_redirect(settings, exc.code)

    response = RedirectResponse(
        f"{settings.frontend_base_url}{result.redirect_path}", status_code=status.HTTP_302_FOUND
    )
    set_session_cookie(response, settings, token=result.session_token, expires_at=result.expires_at)
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    return response


async def _build_me(context: AuthContext, management: ManagementServiceDep) -> MeResponse:
    """Assemble ``/auth/me`` from the context plus the tenants behind its memberships."""
    tenants = {
        tenant.id: tenant for tenant in await management.list_tenants_for(context) if tenant.id
    }
    memberships = [
        MembershipOut(
            tenant_id=membership.tenant_id,
            tenant_slug=tenants[membership.tenant_id].slug
            if membership.tenant_id in tenants
            else "",
            tenant_name=tenants[membership.tenant_id].name
            if membership.tenant_id in tenants
            else "",
            role=membership.role,
        )
        for membership in context.memberships
    ]
    return MeResponse(
        user=UserOut.from_user(context.user),
        effective_role=str(context.effective_role),
        portal_path=context.portal_path,
        memberships=memberships,
        active_tenant_id=management.resolve_active_tenant(context),
    )


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"description": "Not signed in"}},
    summary="The signed-in user, their roles and their portal",
)
async def me(context: CurrentUser, management: ManagementServiceDep) -> MeResponse:
    """Roles are read fresh from the database, so this always reflects the latest change."""
    return await _build_me(context, management)


@router.post("/logout", response_model=LogoutResponse, summary="Sign out and revoke the session")
async def logout(
    request: Request, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> LogoutResponse:
    """Delete the session document and clear the cookie.

    Deliberately not behind :data:`~app.dependencies.auth.CurrentUser`: signing out with an
    already-invalid cookie must still clear it rather than answer 401.
    """
    token = request.cookies.get(settings.session_cookie_name)
    signed_out = await auth.logout(token) if token else False
    clear_session_cookie(response, settings)
    return LogoutResponse(signed_out=signed_out)


@router.post(
    "/invites/accept",
    response_model=MeResponse,
    responses={
        400: {"description": "The invite is expired, used, or addressed to someone else"},
        401: {"description": "Not signed in"},
    },
    summary="Accept an invite as the signed-in user",
)
async def accept_invite(
    body: InviteAcceptRequest,
    context: CurrentUser,
    auth: AuthServiceDep,
    management: ManagementServiceDep,
) -> MeResponse:
    """Join a restaurant with an invite token.

    Someone who signs in *after* being invited never needs this - the callback consumes
    invites for their verified address automatically. It exists for the case where the
    invite arrives while they are already signed in.
    """
    try:
        await auth.accept_invite_token(body.token, context.user)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    refreshed = await auth.context_for(context.user, context.session)
    return await _build_me(refreshed, management)
