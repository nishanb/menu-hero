"""Importing restaurants from Google Business Profile.

Everything but the HTTP to Google is real: the routes, the consent state cookie, the
encryption of the refresh token at rest, the mapping onto a restaurant, and the ownership
rule that whoever imports a business owns it. The double is wired in by ``conftest.py``.

These talk to a real MongoDB through the app and skip when none is reachable.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from conftest import (
    TEST_DATABASE_NAME,
    TEST_MONGODB_URL,
    FakeGoogleBusinessProvider,
    SignIn,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymongo import AsyncMongoClient

from app.core.config import Settings, get_settings
from app.services.google_business import GoogleBusinessError, _api_error_message

OWNER_EMAIL = "owner@example.com"
STATE_COOKIE = "mh_gbp_state"
LOCATION = "locations/100"


def _as(client: TestClient, sign_in: SignIn, email: str) -> None:
    """Become ``email`` in this browser."""
    client.cookies.clear()
    assert sign_in(email).status_code == 302


def _connect(
    client: TestClient, google_business: FakeGoogleBusinessProvider, *, refresh_token: str = "r1"
) -> None:
    """Run the whole consent round trip, as a browser would."""
    start = client.get("/api/v1/google-business/connect")
    assert start.status_code == 307, start.text
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/api/v1/google-business/callback",
        params={"code": google_business.issue_code(refresh_token), "state": state},
    )
    assert callback.status_code == 302, callback.text
    assert "connected=1" in callback.headers["location"]


# ----------------------------------------------------------------------------- connecting


def test_status_reports_configured_but_not_yet_connected(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    status = auth_client.get("/api/v1/google-business/status").json()

    assert status["configured"] is True
    assert status["connection"]["connected"] is False


def test_connecting_stores_a_grant_and_never_returns_the_token(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    _connect(auth_client, google_business)

    body = auth_client.get("/api/v1/google-business/status").json()
    assert body["connection"]["connected"] is True
    assert "business.manage" in body["connection"]["scopes"][0]
    assert "refresh" not in auth_client.get("/api/v1/google-business/status").text


async def test_the_stored_refresh_token_is_encrypted_at_rest(
    auth_client: TestClient,
    sign_in: SignIn,
    google_business: FakeGoogleBusinessProvider,
    auth_settings: Settings,
) -> None:
    """A database dump must not hand over a live Google credential."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business, refresh_token="super-secret-refresh")

    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(TEST_MONGODB_URL)
    try:
        stored = await client[TEST_DATABASE_NAME]["google_connections"].find_one({})
    finally:
        await client.aclose()

    assert stored is not None
    assert "super-secret-refresh" not in str(stored)


def test_a_callback_with_a_mismatched_state_is_refused(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    auth_client.get("/api/v1/google-business/connect")

    response = auth_client.get(
        "/api/v1/google-business/callback",
        params={"code": google_business.issue_code(), "state": "not-the-one"},
    )

    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["location"]
    assert auth_client.get("/api/v1/google-business/status").json()["connection"]["connected"] is (
        False
    )


def test_disconnecting_revokes_at_google_and_forgets_locally(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business, refresh_token="r-drop")

    assert auth_client.delete("/api/v1/google-business/connection").status_code == 204

    assert google_business.revoked == ["r-drop"]
    assert auth_client.get("/api/v1/google-business/status").json()["connection"]["connected"] is (
        False
    )


def test_endpoints_require_a_session(auth_client: TestClient) -> None:
    assert auth_client.get("/api/v1/google-business/status").status_code == 401
    assert auth_client.get("/api/v1/google-business/locations").status_code == 401
    assert auth_client.get("/api/v1/google-business/connect").status_code == 401


# ----------------------------------------------------------------------------- browsing


def test_listing_without_connecting_asks_the_person_to_connect(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    response = auth_client.get("/api/v1/google-business/locations")

    assert response.status_code == 409
    assert response.json()["detail"] == "Connect a Google account first"


def test_locations_come_back_flattened(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)

    body = auth_client.get("/api/v1/google-business/locations").json()

    assert [a["account_name"] for a in body["accounts"]] == ["Spice Group"]
    location = body["locations"][0]
    assert location["title"] == "Spice Garden"
    assert location["address"].startswith("12 Beach Road")
    assert location["imported"] is False


def test_an_unapproved_google_project_says_so_rather_than_failing_silently(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    """The Business Profile APIs are allow-listed per project; that is the common failure."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)
    google_business.failure = GoogleBusinessError("Google refused access: PERMISSION_DENIED")

    response = auth_client.get("/api/v1/google-business/locations")

    assert response.status_code == 502
    assert "PERMISSION_DENIED" in response.json()["detail"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            {
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": (
                        "My Business Account Management API has not been used in project "
                        "1234 before or it is disabled. Enable it by visiting "
                        "https://console.developers.google.com/apis/api/"
                        "mybusinessaccountmanagement.googleapis.com/overview?project=1234"
                    ),
                }
            },
            "Enable it by visiting",
            id="api-switched-off-keeps-google's-console-link",
        ),
        pytest.param(
            {
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": "The caller does not have permission",
                }
            },
            "allow-listed by Google",
            id="not-allow-listed-gets-the-manual-request-note",
        ),
    ],
)
def test_the_two_kinds_of_403_are_reported_differently(
    body: dict[str, object], expected: str
) -> None:
    """Both are HTTP 403 PERMISSION_DENIED, but one is a click and the other is a wait."""
    response = httpx.Response(403, json=body, request=httpx.Request("GET", "https://example"))

    assert expected in _api_error_message(response)


# ----------------------------------------------------------------------------- importing


def test_importing_a_location_creates_a_restaurant_the_caller_owns(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)

    created = auth_client.post("/api/v1/google-business/import", json={"location": LOCATION})

    assert created.status_code == 201, created.text
    tenant = created.json()
    assert tenant["name"] == "Spice Garden"
    assert tenant["slug"] == "spice-garden"
    assert tenant["description"] == "Coastal Karnataka home cooking."
    assert tenant["location_url"] == "https://maps.google.com/?cid=1"
    assert tenant["extras"]["phone"] == "+91 80 1234 5678"
    assert tenant["extras"]["google_place_id"] == "ChIJexample"
    assert tenant["google_location"] == LOCATION

    me = auth_client.get("/api/v1/auth/me").json()
    assert [m["role"] for m in me["memberships"]] == ["owner"]
    assert me["active_tenant_id"] == tenant["id"]


def test_a_location_is_only_imported_once(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)
    assert (
        auth_client.post("/api/v1/google-business/import", json={"location": LOCATION}).status_code
        == 201
    )

    again = auth_client.post("/api/v1/google-business/import", json={"location": LOCATION})

    assert again.status_code == 409
    assert "already been imported" in again.json()["detail"]
    listed = auth_client.get("/api/v1/google-business/locations").json()
    assert listed["locations"][0]["imported"] is True


def test_a_location_the_account_does_not_have_cannot_be_imported(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    """The body only names a location; the server re-reads it rather than trusting it."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)

    response = auth_client.post(
        "/api/v1/google-business/import", json={"location": "locations/999"}
    )

    assert response.status_code == 409
    assert "not in this Google account" in response.json()["detail"]


def test_syncing_refreshes_google_fields_and_leaves_local_ones_alone(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)
    tenant_id = auth_client.post(
        "/api/v1/google-business/import", json={"location": LOCATION}
    ).json()["id"]
    auth_client.patch(f"/api/v1/tenants/{tenant_id}", json={"services": ["dining"]})
    google_business.locations["accounts/1"][0].description = "Now open Sundays."

    synced = auth_client.post("/api/v1/google-business/sync", json={"tenant_id": tenant_id})

    assert synced.status_code == 200, synced.text
    assert synced.json()["description"] == "Now open Sundays."
    assert synced.json()["services"] == ["dining"]  # never came from Google, so untouched


def test_syncing_a_restaurant_that_was_never_imported_is_refused(
    auth_client: TestClient, sign_in: SignIn, google_business: FakeGoogleBusinessProvider
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _connect(auth_client, google_business)
    tenant_id = auth_client.post("/api/v1/tenants", json={"name": "By Hand"}).json()["id"]

    response = auth_client.post("/api/v1/google-business/sync", json={"tenant_id": tenant_id})

    assert response.status_code == 409
    assert "not imported from Google" in response.json()["detail"]


# ----------------------------------------------------------------------------- unavailable


def test_a_deployment_without_a_secret_key_says_so_instead_of_half_working(
    auth_client: TestClient, sign_in: SignIn, auth_settings: Settings
) -> None:
    """There is no feature switch, but there is still a way for this to be unavailable.

    The refresh token is encrypted with a key derived from ``SECRET_KEY``; without one the
    flow would complete consent and then have nowhere safe to put the credential, so it is
    refused up front instead.

    Settings are overridden on the running app rather than by building a second one - two
    apps would open two MongoDB clients on two event loops, which the async driver refuses.
    """
    _as(auth_client, sign_in, OWNER_EMAIL)
    disabled = auth_settings.model_copy(update={"secret_key": SecretStr("")})
    auth_client.app.dependency_overrides[get_settings] = lambda: disabled  # type: ignore[attr-defined]
    try:
        assert auth_client.get("/api/v1/google-business/status").json()["configured"] is False
        assert auth_client.get("/api/v1/google-business/connect").status_code == 503
        assert auth_client.get("/api/v1/google-business/locations").status_code == 503
        assert auth_client.delete("/api/v1/google-business/connection").status_code == 503
    finally:
        auth_client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]
