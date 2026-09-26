"""Shared fixtures: an isolated test environment and a TestClient with lifespan.

The auth fixtures at the bottom need a real MongoDB and skip themselves when none is
reachable at ``TEST_MONGODB_URL`` (default ``mongodb://127.0.0.1:27017``), the same rule
``tests/test_models.py`` uses::

    docker run --rm -d -p 27017:27017 --name mh-mongo mongo:8
    uv run pytest
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.config import Settings, clear_settings_cache, get_settings
from app.core.database import close_client
from app.dependencies.auth import get_google_business_provider, get_google_identity_provider
from app.main import create_app
from app.services.google_business import (
    BusinessAccount,
    BusinessLocation,
    GoogleBusinessError,
    GrantedTokens,
)
from app.services.google_oauth import GoogleAuthError, GoogleIdentity, identity_from_claims

BACKEND_ENV_VARS = (
    "APP_ENV",
    "SECRET_KEY",
    "DATABASE_URL",
    "MONGODB_DATABASE",
    "CORS_ORIGINS",
    "LOG_LEVEL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "FRONTEND_BASE_URL",
    "SESSION_COOKIE_NAME",
    "SESSION_TTL_DAYS",
    "INVITE_TTL_DAYS",
    "BOOTSTRAP_ADMIN_EMAILS",
    "GOOGLE_BUSINESS_REDIRECT_URI",
)
"""Cleared before every test so a developer's real ``.env`` never changes an outcome."""

TEST_MONGODB_URL = os.environ.get("TEST_MONGODB_URL", "mongodb://127.0.0.1:27017")
TEST_DATABASE_NAME = "menuhero_auth_test"
TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
ADMIN_EMAIL = "admin@example.com"
"""Configured as the bootstrap admin, so signing in with it yields a platform admin."""


@pytest.fixture(autouse=True)
def test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every test with APP_ENV=test, no inherited configuration, fresh settings.

    Clearing the environment variables is not enough on its own: ``Settings`` also reads
    the repo-root ``.env``, so a developer with a real ``DATABASE_URL`` or Google client id
    in it would see different results from CI. Disabling ``env_file`` for the duration of
    the session makes the environment the only input, which is what the fixtures below
    then control explicitly.
    """
    for name in BACKEND_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("APP_ENV", "test")
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client for a freshly created app; the context manager runs the lifespan."""
    with TestClient(create_app()) as test_client:
        yield test_client


# --------------------------------------------------------------------- Google test double


class FakeGoogleProvider:
    """Stands in for Google: hands out codes, and trades them back for identities.

    :meth:`exchange_code` runs the *real* claim validation
    (:func:`app.services.google_oauth.identity_from_claims`), so the issuer, audience,
    expiry and ``email_verified`` rules are exercised by the flow tests too.
    """

    def __init__(self, client_id: str = TEST_CLIENT_ID) -> None:
        self.client_id = client_id
        self.codes: dict[str, dict[str, object]] = {}
        self.authorization_urls: list[str] = []

    def issue_code(
        self,
        email: str,
        *,
        sub: str | None = None,
        name: str = "Test Person",
        email_verified: bool = True,
    ) -> str:
        """Register an authorization code that will resolve to this account."""
        code = f"code-{len(self.codes)}-{email}"
        self.codes[code] = {
            "iss": "https://accounts.google.com",
            "aud": self.client_id,
            "exp": (datetime.now(UTC) + timedelta(minutes=5)).timestamp(),
            "sub": sub or f"google-sub-{email}",
            "email": email,
            "email_verified": email_verified,
            "name": name,
            "picture": "",
        }
        return code

    def authorization_url(self, *, state: str) -> str:
        url = f"https://accounts.google.example/authorize?state={state}"
        self.authorization_urls.append(url)
        return url

    async def exchange_code(self, code: str) -> GoogleIdentity:
        claims = self.codes.get(code)
        if claims is None:
            raise GoogleAuthError("Google rejected the authorization code")
        return identity_from_claims(dict(claims), client_id=self.client_id)


class SignIn(Protocol):
    """Signature of the :func:`sign_in` fixture."""

    def __call__(
        self,
        email: str,
        *,
        next_path: str | None = None,
        sub: str | None = None,
        name: str = "Test Person",
        email_verified: bool = True,
    ) -> Response:
        """Sign ``email`` in through the full Google round trip."""
        ...


@pytest.fixture
def google() -> FakeGoogleProvider:
    """The Google double wired into the app by the :func:`auth_client` fixture."""
    return FakeGoogleProvider()


# ------------------------------------------------------------ Google Business Profile double


class FakeGoogleBusinessProvider:
    """Stands in for the Business Profile APIs.

    Mirrors :class:`~app.services.google_business.GoogleBusinessProvider` exactly, so a test
    exercises the real service, routes, encryption and mapping - only the HTTP to Google is
    replaced. ``failure`` makes the next read fail, which is how the allow-list refusal every
    unapproved Google Cloud project sees is reproduced.
    """

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.accounts: list[BusinessAccount] = [
            BusinessAccount(name="accounts/1", account_name="Spice Group", type="PERSONAL")
        ]
        self.locations: dict[str, list[BusinessLocation]] = {
            "accounts/1": [
                BusinessLocation(
                    name="locations/100",
                    account="accounts/1",
                    title="Spice Garden",
                    description="Coastal Karnataka home cooking.",
                    address="12 Beach Road, Mangaluru, KA, 575001, IN",
                    phone="+91 80 1234 5678",
                    website="https://spicegarden.example",
                    maps_url="https://maps.google.com/?cid=1",
                    place_id="ChIJexample",
                    primary_category="Indian restaurant",
                )
            ]
        }
        self.revoked: list[str] = []
        self.failure: GoogleBusinessError | None = None

    def issue_code(self, refresh_token: str = "refresh-1") -> str:
        """Register a consent code that will resolve to this refresh token."""
        code = f"gbp-code-{len(self.codes)}"
        self.codes[code] = refresh_token
        return code

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.example/business?state={state}"

    async def exchange_code(self, code: str) -> GrantedTokens:
        refresh_token = self.codes.get(code)
        if refresh_token is None:
            raise GoogleBusinessError("Google refused the request for a token")
        return GrantedTokens(
            refresh_token=refresh_token,
            access_token="access-1",
            scopes=("https://www.googleapis.com/auth/business.manage",),
        )

    async def access_token(self, refresh_token: str) -> str:
        if refresh_token in self.revoked:
            raise GoogleBusinessError("Google refused the request", code="not_connected")
        return f"access-for-{refresh_token}"

    async def list_accounts(self, access_token: str) -> list[BusinessAccount]:
        if self.failure is not None:
            raise self.failure
        return list(self.accounts)

    async def list_locations(self, access_token: str, *, account: str) -> list[BusinessLocation]:
        if self.failure is not None:
            raise self.failure
        return list(self.locations.get(account, []))

    async def revoke(self, refresh_token: str) -> None:
        self.revoked.append(refresh_token)


@pytest.fixture
def google_business() -> FakeGoogleBusinessProvider:
    """The Business Profile double wired into the app by the :func:`auth_client` fixture."""
    return FakeGoogleBusinessProvider()


# --------------------------------------------------------------------- database-backed app


_mongo_reachable: bool | None = None
"""Remembered across the session: probing an absent server costs a full timeout each time."""


@pytest.fixture
async def mongo_available() -> AsyncIterator[None]:
    """Skip the test unless a MongoDB is reachable, and drop the test database first."""
    global _mongo_reachable
    if _mongo_reachable is False:
        pytest.skip(f"no MongoDB at {TEST_MONGODB_URL}")
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        TEST_MONGODB_URL, serverSelectionTimeoutMS=1500
    )
    try:
        await client.admin.command("ping")
    except PyMongoError:
        _mongo_reachable = False
        await client.aclose()
        pytest.skip(f"no MongoDB at {TEST_MONGODB_URL}")
    _mongo_reachable = True
    finally_close = client
    await client.drop_database(TEST_DATABASE_NAME)
    try:
        yield
    finally:
        await finally_close.drop_database(TEST_DATABASE_NAME)
        await finally_close.aclose()


@pytest.fixture
async def auth_settings(
    mongo_available: None, monkeypatch: pytest.MonkeyPatch, google: FakeGoogleProvider
) -> Settings:
    """Settings pointing at the test database with Google sign-in configured."""
    monkeypatch.setenv("DATABASE_URL", TEST_MONGODB_URL)
    monkeypatch.setenv("MONGODB_DATABASE", TEST_DATABASE_NAME)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", google.client_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAILS", ADMIN_EMAIL)
    # The Business Profile import needs a SECRET_KEY: the refresh token is encrypted at
    # rest with a key derived from it.
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    clear_settings_cache()
    return get_settings()


@pytest.fixture
async def auth_client(
    auth_settings: Settings,
    google: FakeGoogleProvider,
    google_business: FakeGoogleBusinessProvider,
) -> AsyncIterator[TestClient]:
    """A client whose app talks to the test database and to the Google double.

    ``follow_redirects=False`` because the sign-in endpoints answer *with* redirects - the
    tests assert on ``Location`` and ``Set-Cookie``, not on whatever the frontend serves.
    """
    app = create_app(auth_settings)
    app.dependency_overrides[get_google_identity_provider] = lambda: google
    app.dependency_overrides[get_google_business_provider] = lambda: google_business
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    await close_client()


# --------------------------------------------------------------------- sign-in helper


@pytest.fixture
def sign_in(auth_client: TestClient, google: FakeGoogleProvider) -> SignIn:
    """Run a whole Google round trip and return the callback response.

    The client keeps the cookie jar, so afterwards it *is* that signed-in browser. Call
    ``auth_client.cookies.clear()`` to act as a different one.
    """

    def _sign_in(
        email: str,
        *,
        next_path: str | None = None,
        sub: str | None = None,
        name: str = "Test Person",
        email_verified: bool = True,
    ) -> Response:
        params = {"next": next_path} if next_path else None
        start = auth_client.get("/api/v1/auth/google", params=params)
        assert start.status_code == 307, start.text
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        code = google.issue_code(email, sub=sub, name=name, email_verified=email_verified)
        callback: Response = auth_client.get(
            "/api/v1/auth/google/callback", params={"code": code, "state": state}
        )
        return callback

    return _sign_in
