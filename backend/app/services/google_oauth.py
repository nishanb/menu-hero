"""Google sign-in: the authorization-code half of OpenID Connect.

    /auth/google  -> 307 to Google  -> user consents  -> /auth/google/callback?code=...
                  -> POST to Google's token endpoint  -> id_token -> verified identity

The parts that are easy to get subtly and dangerously wrong are delegated to libraries:

* **authlib** (`OAuth2Client`) builds the authorization URL - response type, scope encoding
  and redirect handling per RFC 6749, rather than a hand-assembled query string.
* **joserfc** verifies the ``id_token``: it fetches Google's JWKS, checks the RSA/ECDSA
  signature against the key named by the token's ``kid``, and validates ``iss``, ``aud``,
  ``exp`` and ``sub`` through a claims registry. Nothing here parses a JWT by hand, and the
  permitted algorithms are pinned so a token can never talk us into ``none``.

The token POST itself is a plain ``httpx`` call: authlib's async client lives in
``authlib.integrations.httpx_client``, which authlib 1.8 deprecates in favour of an
httpx2 build, and adopting a deprecated integration for one documented form POST buys
nothing. The security-critical work is in joserfc's hands either way.

:class:`GoogleIdentityProvider` is the seam the tests replace - nothing in the auth service
knows about HTTP to Google.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.oauth2.client import OAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from pydantic import BaseModel, Field

from app.core.config import Settings

logger = logging.getLogger(__name__)

SCOPES = ("openid", "email", "profile")
"""The minimum that yields a stable subject, an email and a display name."""

VALID_ISSUERS: tuple[str, ...] = ("https://accounts.google.com", "accounts.google.com")
"""Google issues tokens under both spellings."""

SIGNING_ALGORITHMS = ("RS256", "ES256")
"""Pinned: an unconstrained verifier can be argued into accepting an unsigned token."""

CLOCK_SKEW_SECONDS = 60
"""Tolerance applied to time-based claims."""

TOKEN_REQUEST_TIMEOUT_SECONDS = 10.0
JWKS_TIMEOUT_SECONDS = 10.0
JWKS_CACHE_SECONDS = 3600
"""Google rotates signing keys slowly; a stale key is handled by the retry in
:meth:`GoogleOAuthClient.verified_claims`, so an hour is safe."""


class GoogleAuthError(RuntimeError):
    """Google refused the exchange, or returned a token this client will not accept."""


class GoogleIdentity(BaseModel):
    """The verified claims this application uses out of a Google ``id_token``."""

    sub: str = Field(min_length=1, description="Stable, per-client account identifier.")
    email: str = Field(min_length=3)
    email_verified: bool = False
    name: str = ""
    picture: str = ""


class GoogleIdentityProvider(Protocol):
    """What the auth service needs from Google (and what a test double provides)."""

    def authorization_url(self, *, state: str) -> str:
        """URL to send the browser to, carrying the CSRF ``state``."""
        ...

    async def exchange_code(self, code: str) -> GoogleIdentity:
        """Trade an authorization ``code`` for the signed-in person's identity.

        Raises :class:`GoogleAuthError` for anything that is not a usable identity.
        """
        ...


def claims_registry(client_id: str) -> jwt.JWTClaimsRegistry:
    """The claim rules every ``id_token`` must satisfy, as a joserfc registry."""
    return jwt.JWTClaimsRegistry(
        leeway=CLOCK_SKEW_SECONDS,
        iss={"essential": True, "values": list(VALID_ISSUERS)},
        aud={"essential": True, "value": client_id},
        exp={"essential": True},
        sub={"essential": True},
        email={"essential": True},
    )


def identity_from_claims(claims: dict[str, Any], *, client_id: str) -> GoogleIdentity:
    """Validate the claims and project them onto :class:`GoogleIdentity`.

    Shared by the real client and by test doubles so both enforce the same rules. The
    standard claims go through joserfc; ``email_verified`` is application policy, not part
    of JWT validation, so it is checked here - without it anyone could claim an address
    they do not control and pick up the invites addressed to it.
    """
    try:
        claims_registry(client_id).validate(claims)
    except JoseError as exc:
        raise GoogleAuthError(f"id_token rejected: {exc.description}") from exc
    if not claims.get("email_verified", False):
        raise GoogleAuthError("Google account has no verified email address")
    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=str(claims["email"]),
        email_verified=True,
        name=str(claims.get("name") or ""),
        picture=str(claims.get("picture") or ""),
    )


@dataclass
class _JwksCache:
    """Google's signing keys, kept for :data:`JWKS_CACHE_SECONDS`.

    Module-level, so it is shared by the per-request client instances. No lock: two
    concurrent sign-ins racing on a cold cache cost one redundant fetch, which is cheaper
    than serialising every sign-in behind one.
    """

    key_set: KeySet | None = None
    fetched_at: float = 0.0

    def get(self) -> KeySet | None:
        """The cached key set while it is fresh, else ``None``."""
        if self.key_set is None or time.monotonic() - self.fetched_at > JWKS_CACHE_SECONDS:
            return None
        return self.key_set

    def put(self, key_set: KeySet) -> None:
        """Replace the cached key set."""
        self.key_set = key_set
        self.fetched_at = time.monotonic()


_jwks_cache = _JwksCache()


def reset_jwks_cache() -> None:
    """Forget the cached signing keys (tests, and after a rotation)."""
    _jwks_cache.key_set = None
    _jwks_cache.fetched_at = 0.0


class GoogleOAuthClient:
    """Talks to the real Google endpoints configured in :class:`~app.core.config.Settings`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _oauth_client(self) -> OAuth2Client:
        """authlib's protocol client. ``session=None``: it is only used to build URLs here."""
        return OAuth2Client(
            None,
            client_id=self._settings.google_client_id,
            client_secret=self._settings.google_client_secret.get_secret_value(),
            redirect_uri=self._settings.google_redirect_uri,
            scope=" ".join(SCOPES),
        )

    def authorization_url(self, *, state: str) -> str:
        """Build the consent-screen URL.

        ``prompt=select_account`` so a shared machine does not silently reuse the last
        Google account; no ``access_type=offline`` because nothing here calls Google APIs
        later, so a refresh token would be a credential stored for no reason.
        """
        url, _ = self._oauth_client().create_authorization_url(
            self._settings.google_authorization_endpoint,
            state=state,
            prompt="select_account",
        )
        return str(url)

    async def exchange_code(self, code: str) -> GoogleIdentity:
        """Exchange ``code`` at Google's token endpoint and verify the ``id_token``."""
        form = {
            "code": code,
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret.get_secret_value(),
            "redirect_uri": self._settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            async with httpx.AsyncClient(timeout=TOKEN_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(self._settings.google_token_endpoint, data=form)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("Could not reach Google's token endpoint") from exc
        if response.status_code != httpx.codes.OK:
            # Google's body echoes the code and can carry client detail; log the status only.
            logger.warning("google token exchange failed: status=%s", response.status_code)
            raise GoogleAuthError("Google rejected the authorization code")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleAuthError("Google's token response was not JSON") from exc
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str):
            raise GoogleAuthError("Google's token response carried no id_token")
        claims = await self.verified_claims(id_token)
        return identity_from_claims(claims, client_id=self._settings.google_client_id)

    async def _key_set(self, *, refresh: bool = False) -> KeySet:
        """Google's public signing keys, from the cache unless ``refresh`` is set."""
        if not refresh:
            cached = _jwks_cache.get()
            if cached is not None:
                return cached
        try:
            async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
                response = await client.get(self._settings.google_jwks_uri)
                response.raise_for_status()
            key_set = KeySet.import_key_set(response.json())
        except (httpx.HTTPError, ValueError, JoseError) as exc:
            raise GoogleAuthError("Could not fetch Google's signing keys") from exc
        _jwks_cache.put(key_set)
        return key_set

    async def verified_claims(self, id_token: str) -> dict[str, Any]:
        """Verify an ``id_token``'s signature against Google's JWKS and return its claims.

        Public because the Business Profile grant (:mod:`app.services.google_business`) gets
        an ``id_token`` of its own back and needs it checked the same way; a second copy of
        the JWKS cache and the algorithm pinning is exactly what should not exist.

        A failure is retried once against freshly fetched keys: Google rotates signing
        keys, and a cached set that predates a rotation is the ordinary cause.
        """
        try:
            token = jwt.decode(id_token, await self._key_set(), algorithms=list(SIGNING_ALGORITHMS))
        except JoseError:
            try:
                token = jwt.decode(
                    id_token,
                    await self._key_set(refresh=True),
                    algorithms=list(SIGNING_ALGORITHMS),
                )
            except JoseError as exc:
                logger.warning("id_token signature verification failed: %s", type(exc).__name__)
                raise GoogleAuthError("id_token signature could not be verified") from exc
        return dict(token.claims)
