"""Importing restaurants from Google Business Profile.

    GET    /api/v1/google-business/status      -> is it set up, and is this person connected
    GET    /api/v1/google-business/connect     -> 307 to Google's consent screen
    GET    /api/v1/google-business/callback    -> stores the grant, back to the app
    DELETE /api/v1/google-business/connection  -> revoke and forget the grant
    GET    /api/v1/google-business/locations   -> the businesses the person administers
    POST   /api/v1/google-business/import      -> one location, as a restaurant they own
    POST   /api/v1/google-business/sync        -> refresh an imported restaurant

``connect`` and ``callback`` are browser navigations, so - exactly as with sign-in - every
failure ends as a redirect carrying an ``error`` code rather than as JSON the person would
see as raw text.

This is a *second* OAuth grant, separate from sign-in: its own scope, its own redirect URI,
its own state cookie. See :mod:`app.services.google_business` for why.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.routes.auth import cookie_kwargs
from app.core.config import Settings
from app.dependencies.auth import CurrentUser, GoogleBusinessServiceDep, OptionalUser
from app.dependencies.settings import SettingsDep
from app.models import PyObjectId
from app.schemas.google_business import (
    BusinessAccountOut,
    BusinessImportRequest,
    BusinessLocationListResponse,
    BusinessLocationOut,
    BusinessSyncRequest,
    GoogleBusinessStatusResponse,
    GoogleConnectionOut,
)
from app.schemas.management import TenantOut
from app.services.auth_service import OAuthState, is_safe_next_path
from app.services.google_business import GoogleBusinessError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google-business")

STATE_COOKIE_NAME = "mh_gbp_state"
"""Its own cookie: a sign-in round trip and a connect round trip must not be interchangeable."""

STATE_COOKIE_MAX_AGE_SECONDS = 600

DEFAULT_RETURN_PATH = "/onboarding"
"""Where the browser lands after connecting, when it asked for nowhere in particular."""

NOT_CONFIGURED_DETAIL = (
    "This deployment cannot import from Google Business Profile: it needs a Google OAuth "
    "client and a SECRET_KEY to encrypt the connection with"
)

UNAVAILABLE_RESPONSE: dict[int | str, dict[str, Any]] = {
    503: {"description": "This deployment has no Google client or no SECRET_KEY"}
}
UPSTREAM_RESPONSE: dict[int | str, dict[str, Any]] = {
    502: {"description": "Google refused the request, or the API is not allow-listed"}
}


def _require_configured(settings: Settings) -> None:
    """503 unless this deployment can actually run the import."""
    if not settings.google_business_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_CONFIGURED_DETAIL
        )


def _upstream(exc: GoogleBusinessError) -> HTTPException:
    """Map a Google failure onto a status the UI can act on.

    A dead grant is 409, not 502: it is the person's to fix by connecting again, and the UI
    shows them the button rather than "something went wrong at Google".
    """
    if exc.code == "not_connected":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if exc.code in {"already_imported", "not_imported", "location_not_found"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def _return_redirect(settings: Settings, path: str, **query: str) -> RedirectResponse:
    """Send the browser back into the app, clearing the state cookie on the way out."""
    target = path if is_safe_next_path(path) else DEFAULT_RETURN_PATH
    suffix = f"?{urlencode(query)}" if query else ""
    response = RedirectResponse(
        f"{settings.frontend_base_url}{target}{suffix}", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    return response


@router.get(
    "/status",
    response_model=GoogleBusinessStatusResponse,
    summary="Whether the import is available, and whether the caller has connected",
)
async def connection_status(
    context: CurrentUser, google: GoogleBusinessServiceDep, settings: SettingsDep
) -> GoogleBusinessStatusResponse:
    """Answers without calling Google, so the onboarding page renders immediately."""
    if not settings.google_business_configured:
        return GoogleBusinessStatusResponse(configured=False)
    return GoogleBusinessStatusResponse(
        configured=True,
        connection=GoogleConnectionOut.from_connection(await google.connection_for(context)),
    )


@router.get(
    "/connect",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses={307: {"description": "Redirect to Google's consent screen"}, **UNAVAILABLE_RESPONSE},
    summary="Connect a Google account with Business Profile access",
)
async def connect(
    context: CurrentUser,
    google: GoogleBusinessServiceDep,
    settings: SettingsDep,
    next: Annotated[
        str | None,
        Query(max_length=512, description="Same-origin path to return to; ignored otherwise."),
    ] = None,
) -> RedirectResponse:
    """Behind :data:`~app.dependencies.auth.CurrentUser`: the grant is stored against a person.

    A signed-out browser reaching here would otherwise complete a consent round trip with
    nowhere to put the result.
    """
    _require_configured(settings)
    state = OAuthState.create(next or DEFAULT_RETURN_PATH)
    response = RedirectResponse(
        google.authorization_url(state=state.state), status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    response.set_cookie(
        STATE_COOKIE_NAME,
        state.encode(),
        max_age=STATE_COOKIE_MAX_AGE_SECONDS,
        **cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return response


@router.get(
    "/callback",
    status_code=status.HTTP_302_FOUND,
    responses={302: {"description": "Back to the app, connected or with ?error=..."}},
    summary="Google Business Profile consent callback",
)
async def callback(
    request: Request,
    context: OptionalUser,
    google: GoogleBusinessServiceDep,
    settings: SettingsDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """Store the grant and return to wherever the connect request came from.

    ``OptionalUser`` rather than ``CurrentUser``: a 401 here would be a bare JSON body in
    the middle of a browser navigation, so a lost session is redirected like any other
    failure instead.
    """
    expected = OAuthState.decode(request.cookies.get(STATE_COOKIE_NAME) or "")
    destination = expected.next_path or DEFAULT_RETURN_PATH

    if error is not None:
        logger.info("google business consent declined: %s", error)
        return _return_redirect(settings, destination, error="google_declined")
    if not settings.google_business_configured:
        return _return_redirect(settings, destination, error="not_configured")
    if context is None:
        return _return_redirect(settings, destination, error="signed_out")
    if (
        not code
        or not state
        or not expected.state
        or not secrets.compare_digest(expected.state, state)
    ):
        return _return_redirect(settings, destination, error="invalid_state")

    try:
        await google.store_grant(code=code, context=context)
    except GoogleBusinessError as exc:
        logger.info("google business connect failed: %s", exc.code)
        return _return_redirect(settings, destination, error=exc.code)
    return _return_redirect(settings, destination, connected="1")


@router.delete(
    "/connection",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=UNAVAILABLE_RESPONSE,
    summary="Disconnect the Google account",
)
async def disconnect(
    context: CurrentUser, google: GoogleBusinessServiceDep, settings: SettingsDep
) -> Response:
    """Revokes the grant at Google and deletes it here. Imported restaurants are untouched."""
    _require_configured(settings)
    try:
        await google.disconnect(context)
    except GoogleBusinessError as exc:
        raise _upstream(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/locations",
    response_model=BusinessLocationListResponse,
    responses={
        409: {"description": "Not connected, or the grant is no longer accepted"},
        **UNAVAILABLE_RESPONSE,
        **UPSTREAM_RESPONSE,
    },
    summary="The businesses the connected account administers",
)
async def list_locations(
    context: CurrentUser,
    google: GoogleBusinessServiceDep,
    settings: SettingsDep,
    account: Annotated[
        str | None, Query(max_length=200, description="Limit to one account resource name.")
    ] = None,
) -> BusinessLocationListResponse:
    """Each location says whether a restaurant has already been imported from it."""
    _require_configured(settings)
    try:
        accounts, locations = await google.list_locations(context, account=account)
    except GoogleBusinessError as exc:
        raise _upstream(exc) from exc
    already = await google.imported_locations()
    return BusinessLocationListResponse(
        accounts=[BusinessAccountOut.from_account(item) for item in accounts],
        locations=[
            BusinessLocationOut.from_location(item, imported=item.name in already)
            for item in locations
        ],
    )


@router.post(
    "/import",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Not connected, or that location is already imported"},
        **UNAVAILABLE_RESPONSE,
        **UPSTREAM_RESPONSE,
    },
    summary="Import one business as a restaurant",
)
async def import_location(
    body: BusinessImportRequest,
    context: CurrentUser,
    google: GoogleBusinessServiceDep,
    settings: SettingsDep,
) -> TenantOut:
    """The caller becomes the owner, exactly as if they had filled the form in by hand."""
    _require_configured(settings)
    try:
        tenant = await google.import_location(location_name=body.location, context=context)
    except GoogleBusinessError as exc:
        raise _upstream(exc) from exc
    return TenantOut.from_tenant(tenant)


@router.post(
    "/sync",
    response_model=TenantOut,
    responses={
        403: {"description": "Not an owner of this restaurant"},
        409: {"description": "Not connected, or the restaurant was not imported from Google"},
        **UNAVAILABLE_RESPONSE,
        **UPSTREAM_RESPONSE,
    },
    summary="Refresh an imported restaurant from Google (owner or admin)",
)
async def sync_location(
    body: BusinessSyncRequest,
    context: CurrentUser,
    google: GoogleBusinessServiceDep,
    settings: SettingsDep,
) -> TenantOut:
    """Re-reads the location and overwrites the fields that came from Google.

    Anything the owner typed here that Google does not know about - services, diet options,
    the logo - is left alone.
    """
    _require_configured(settings)
    tenant_id: PyObjectId = body.tenant_id
    try:
        tenant = await google.sync_location(tenant_id=tenant_id, context=context)
    except GoogleBusinessError as exc:
        raise _upstream(exc) from exc
    return TenantOut.from_tenant(tenant)
