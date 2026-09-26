"""Google Business Profile: the second, opt-in OAuth grant and the two read APIs.

This is deliberately *not* an extension of :mod:`app.services.google_oauth`. Sign-in asks
for ``openid email profile`` and stores no credential; importing a restaurant asks for
``business.manage``, needs ``access_type=offline``, and comes back with a refresh token
that is a real credential at rest. Widening the sign-in scopes would put every person who
ever signs in through a business-management consent screen and store a token for people
who never asked to import anything, so the two flows keep separate scopes, separate
redirect URIs and separate state cookies.

    /google-business/connect   -> Google consent (business.manage, offline, consent)
    /google-business/callback  -> refresh token, encrypted, in `google_connections`
    /google-business/locations -> accounts -> locations, mapped to a draft restaurant

Two Google services are involved, as Google splits them:

* **Account Management API** - ``GET /v1/accounts`` lists the Business Profile accounts the
  person administers.
* **Business Information API** - ``GET /v1/{account}/locations`` lists the locations of one
  account, and requires an explicit ``readMask``.

Both must be *enabled* on the Cloud project and the project must be *allow-listed* by
Google. Those are separate steps that fail identically - HTTP 403, ``PERMISSION_DENIED`` -
and are minutes apart or days apart respectively, so :func:`_api_error_message` keeps them
distinct by Google's own wording. Either way the route turns it into a 502 with the reason
attached.

:class:`GoogleBusinessProvider` is the seam the tests replace, exactly as
:class:`~app.services.google_oauth.GoogleIdentityProvider` is for sign-in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.oauth2.client import OAuth2Client
from pydantic import BaseModel, Field

from app.core.config import GOOGLE_BUSINESS_SCOPE, Settings
from app.services.google_oauth import GoogleAuthError, GoogleOAuthClient

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15.0

CONSENT_SCOPES = (GOOGLE_BUSINESS_SCOPE, "openid", "email")
"""``openid email`` rides along so the token response carries an ``id_token`` and the UI can
say *which* Google account is connected. It costs no extra consent - the person granted both
at sign-in, and ``include_granted_scopes`` means they are held already."""

LOCATION_READ_MASK = ",".join(
    (
        "name",
        "title",
        "storeCode",
        "profile",
        "websiteUri",
        "phoneNumbers",
        "categories",
        "storefrontAddress",
        "latlng",
        "metadata",
    )
)
"""The Business Information API refuses a locations call without a ``readMask``."""

MAX_PAGE_SIZE = 100
"""The maximum the locations endpoint accepts."""

MAX_PAGES = 10
"""Stops an unbounded walk if Google keeps handing back page tokens."""


class GoogleBusinessError(RuntimeError):
    """A Business Profile call could not be completed. The message is caller-facing."""

    def __init__(self, message: str, *, code: str = "google_business_failed") -> None:
        super().__init__(message)
        self.code = code


class GoogleBusinessNotConnectedError(GoogleBusinessError):
    """The person has not granted access, or the grant is no longer usable."""

    def __init__(self, message: str = "Connect a Google account first") -> None:
        super().__init__(message, code="not_connected")


@dataclass(frozen=True, slots=True)
class GrantedTokens:
    """What Google returns from the ``business.manage`` code exchange."""

    refresh_token: str
    access_token: str
    scopes: tuple[str, ...]
    email: str = ""
    """The address of the connected account, for showing which one it is. Best-effort: it is
    read from a *verified* ``id_token`` when the response carries one, and left empty
    otherwise rather than trusted unverified."""


class BusinessAccount(BaseModel):
    """One Business Profile account (a personal account or a business group)."""

    name: str = Field(description="Resource name, e.g. ``accounts/123``.")
    account_name: str = ""
    type: str = ""
    verification_state: str = ""

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> BusinessAccount:
        """Project the Account Management API's camelCase body."""
        return cls(
            name=str(raw.get("name") or ""),
            account_name=str(raw.get("accountName") or ""),
            type=str(raw.get("type") or ""),
            verification_state=str(raw.get("verificationState") or ""),
        )


class BusinessLocation(BaseModel):
    """One location, flattened to the fields a restaurant profile is built from."""

    name: str = Field(description="Resource name, e.g. ``locations/456``.")
    account: str = Field(default="", description="Resource name of the owning account.")
    title: str = ""
    description: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    maps_url: str = ""
    place_id: str = ""
    store_code: str = ""
    primary_category: str = ""

    @classmethod
    def from_api(cls, raw: dict[str, Any], *, account: str) -> BusinessLocation:
        """Project the Business Information API's ``Location`` onto flat fields.

        Every field is optional in practice - a location that has never been completed
        carries little more than a name - so each is read defensively.
        """
        metadata = _mapping(raw.get("metadata"))
        categories = _mapping(raw.get("categories"))
        primary = _mapping(categories.get("primaryCategory"))
        phones = _mapping(raw.get("phoneNumbers"))
        return cls(
            name=str(raw.get("name") or ""),
            account=account,
            title=str(raw.get("title") or ""),
            description=str(_mapping(raw.get("profile")).get("description") or ""),
            address=_format_address(_mapping(raw.get("storefrontAddress"))),
            phone=str(phones.get("primaryPhone") or ""),
            website=_https_only(str(raw.get("websiteUri") or "")),
            maps_url=_https_only(str(metadata.get("mapsUri") or "")),
            place_id=str(metadata.get("placeId") or ""),
            store_code=str(raw.get("storeCode") or ""),
            primary_category=str(primary.get("displayName") or ""),
        )


def _mapping(value: object) -> dict[str, Any]:
    """``value`` as a dict, or an empty one - Google omits absent sub-objects entirely."""
    return value if isinstance(value, dict) else {}


def _https_only(url: str) -> str:
    """Drop anything that is not an ``https://`` URL; these end up in ``href`` attributes."""
    return url if url.startswith("https://") else ""


def _format_address(address: dict[str, Any]) -> str:
    """Render a ``PostalAddress`` as one line, in the order Google gives its parts."""
    lines = address.get("addressLines")
    parts: list[str] = [str(line) for line in lines if str(line).strip()] if lines else []
    for key in ("locality", "administrativeArea", "postalCode", "regionCode"):
        value = str(address.get(key) or "").strip()
        if value:
            parts.append(value)
    return ", ".join(parts)


class GoogleBusinessProvider(Protocol):
    """What the import service needs from Google (and what a test double provides)."""

    def authorization_url(self, *, state: str) -> str:
        """Consent URL for the ``business.manage`` scope, carrying the CSRF ``state``."""
        ...

    async def exchange_code(self, code: str) -> GrantedTokens:
        """Trade the authorization ``code`` for a refresh token and a first access token."""
        ...

    async def access_token(self, refresh_token: str) -> str:
        """Mint a short-lived access token from a stored refresh token."""
        ...

    async def list_accounts(self, access_token: str) -> list[BusinessAccount]:
        """The Business Profile accounts the connected person administers."""
        ...

    async def list_locations(self, access_token: str, *, account: str) -> list[BusinessLocation]:
        """The locations of one account."""
        ...

    async def revoke(self, refresh_token: str) -> None:
        """Tell Google to drop the grant. Best effort: failure is logged, never raised."""
        ...


class GoogleBusinessClient:
    """Talks to the real Google endpoints configured in :class:`~app.core.config.Settings`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Reused only to verify the id_token that comes back with the grant: the signature
        # checking, the JWKS cache and the claim registry already live there, and a second
        # copy of that is the last thing this module should grow.
        self._identity = GoogleOAuthClient(settings)

    # ------------------------------------------------------------------ consent

    def authorization_url(self, *, state: str) -> str:
        """Build the consent URL for the business scope.

        ``access_type=offline`` with ``prompt=consent`` because a refresh token is what the
        import needs and Google only re-issues one when consent is re-granted explicitly -
        without both, a second connection attempt returns an access token alone and the
        stored grant silently stays empty. ``include_granted_scopes`` makes this an
        *incremental* authorisation, so the sign-in scopes already held are not dropped.
        """
        client = OAuth2Client(
            None,
            client_id=self._settings.google_client_id,
            client_secret=self._settings.google_client_secret.get_secret_value(),
            redirect_uri=self._settings.google_business_redirect_uri,
            scope=" ".join(CONSENT_SCOPES),
        )
        url, _ = client.create_authorization_url(
            self._settings.google_authorization_endpoint,
            state=state,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        return str(url)

    async def exchange_code(self, code: str) -> GrantedTokens:
        """Exchange ``code`` for tokens, and refuse a grant with no refresh token in it."""
        payload = await self._token_request(
            {
                "code": code,
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "redirect_uri": self._settings.google_business_redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        refresh_token = payload.get("refresh_token")
        access_token = payload.get("access_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise GoogleBusinessError(
                "Google did not return a refresh token. Remove MenuHero from your Google "
                "account's third-party access and connect again.",
                code="no_refresh_token",
            )
        if not isinstance(access_token, str) or not access_token:
            raise GoogleBusinessError("Google did not return an access token")
        granted = str(payload.get("scope") or "")
        return GrantedTokens(
            refresh_token=refresh_token,
            access_token=access_token,
            scopes=tuple(scope for scope in granted.split(" ") if scope),
            email=await self._connected_email(payload.get("id_token")),
        )

    async def _connected_email(self, id_token: object) -> str:
        """The address of the account that just granted access, or ``""``.

        Cosmetic - it only labels the connection in the UI - so a token that is absent or
        fails verification costs the label, never the grant.
        """
        if not isinstance(id_token, str) or not id_token:
            return ""
        try:
            claims = await self._identity.verified_claims(id_token)
        except GoogleAuthError:
            logger.info("google business grant carried no verifiable id_token; email omitted")
            return ""
        email = claims.get("email")
        return str(email) if isinstance(email, str) and claims.get("email_verified") else ""

    async def access_token(self, refresh_token: str) -> str:
        """Refresh an access token; a refused refresh means the grant is gone for good."""
        try:
            payload = await self._token_request(
                {
                    "refresh_token": refresh_token,
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret.get_secret_value(),
                    "grant_type": "refresh_token",
                }
            )
        except GoogleBusinessError as exc:
            if exc.code == "token_refused":
                raise GoogleBusinessNotConnectedError(
                    "Google no longer accepts this connection. Connect the account again."
                ) from exc
            raise
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise GoogleBusinessError("Google did not return an access token")
        return token

    async def revoke(self, refresh_token: str) -> None:
        """Revoke the grant at Google. Never raises: the local record is deleted regardless."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                await client.post(
                    self._settings.google_revoke_endpoint, data={"token": refresh_token}
                )
        except httpx.HTTPError as exc:
            logger.warning("could not revoke google grant remotely: %s", exc)

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        """POST to Google's token endpoint and return the parsed body."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(self._settings.google_token_endpoint, data=form)
        except httpx.HTTPError as exc:
            raise GoogleBusinessError("Could not reach Google's token endpoint") from exc
        if response.status_code != httpx.codes.OK:
            # The body echoes the code and the client id; log the status only.
            logger.warning("google business token request failed: status=%s", response.status_code)
            raise GoogleBusinessError(
                "Google refused the request for a token", code="token_refused"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleBusinessError("Google's token response was not JSON") from exc
        if not isinstance(payload, dict):
            raise GoogleBusinessError("Google's token response was not an object")
        return payload

    # ------------------------------------------------------------------ the two read APIs

    async def list_accounts(self, access_token: str) -> list[BusinessAccount]:
        """Every Business Profile account the connected person administers."""
        accounts: list[BusinessAccount] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {"pageSize": MAX_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            body = await self._get(
                f"{self._settings.google_account_management_base_url}/accounts",
                access_token=access_token,
                params=params,
            )
            accounts.extend(
                BusinessAccount.from_api(raw)
                for raw in body.get("accounts", [])
                if isinstance(raw, dict)
            )
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return accounts

    async def list_locations(self, access_token: str, *, account: str) -> list[BusinessLocation]:
        """Every location under one account, with the fields a restaurant needs."""
        locations: list[BusinessLocation] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {
                "readMask": LOCATION_READ_MASK,
                "pageSize": MAX_PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            body = await self._get(
                f"{self._settings.google_business_information_base_url}/{account}/locations",
                access_token=access_token,
                params=params,
            )
            locations.extend(
                BusinessLocation.from_api(raw, account=account)
                for raw in body.get("locations", [])
                if isinstance(raw, dict)
            )
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return locations

    async def _get(
        self, url: str, *, access_token: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        """One authenticated GET, with Google's error reason surfaced to the caller."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {access_token}"}
                )
        except httpx.HTTPError as exc:
            raise GoogleBusinessError("Could not reach the Google Business Profile API") from exc
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise GoogleBusinessNotConnectedError(
                "Google rejected the connection. Connect the account again."
            )
        if response.status_code != httpx.codes.OK:
            raise GoogleBusinessError(_api_error_message(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleBusinessError(
                "The Google Business Profile API did not return JSON"
            ) from exc
        return payload if isinstance(payload, dict) else {}


ALLOW_LIST_HELP = (
    "Google refused access to the Business Profile API. The Cloud project has to be "
    "allow-listed by Google before these APIs answer at all - that is a manual request, "
    "through the access form in Google's Business Profile API documentation, not a setting."
)

API_DISABLED_MARKERS = ("has not been used in project", "is disabled", "not enabled")
"""Fingerprints of Google's *other* 403.

A project that simply has not switched the two APIs on gets the same HTTP 403 and the same
``PERMISSION_DENIED`` status as one that is not allow-listed, but a completely different
message - one that names the API and carries a console link that fixes it in a click. The
two are minutes apart or days apart depending which it is, so they must not be reported
identically.
"""


def _api_error_message(response: httpx.Response) -> str:
    """Turn Google's error envelope into one sentence for the person who clicked Import."""
    status = ""
    message = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = _mapping(body.get("error"))
        status = str(error.get("status") or "")
        message = str(error.get("message") or "")
    # The message is logged in full: it is the only thing that says *why* a 403 happened,
    # and an operator staring at a refusal has nowhere else to look.
    logger.warning(
        "google business api error: http=%s status=%s message=%s",
        response.status_code,
        status or "unknown",
        message or "(none)",
    )
    if status == "PERMISSION_DENIED" or response.status_code == httpx.codes.FORBIDDEN:
        # Hand back Google's own words when they are the actionable ones; ours only when
        # they add something Google's do not.
        if message and any(marker in message.lower() for marker in API_DISABLED_MARKERS):
            return message
        return ALLOW_LIST_HELP
    return message or f"The Google Business Profile API answered {response.status_code}"
