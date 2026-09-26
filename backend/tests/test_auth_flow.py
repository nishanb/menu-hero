"""The onboarding flow end to end: Google round trip, session, portal, invites.

These talk to a real MongoDB through the app and skip when none is reachable (see
``tests/conftest.py``).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import ADMIN_EMAIL, FakeGoogleProvider, SignIn
from fastapi.testclient import TestClient

SESSION_COOKIE = "mh_session"
STATE_COOKIE = "mh_oauth_state"


# ----------------------------------------------------------------------------- start


def test_google_login_redirects_to_google_and_remembers_state(
    auth_client: TestClient, google: FakeGoogleProvider
) -> None:
    response = auth_client.get("/api/v1/auth/google")

    assert response.status_code == 307
    assert response.headers["location"] == google.authorization_urls[-1]
    state_cookie = response.cookies[STATE_COOKIE]
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert state_cookie.startswith(state)
    assert "httponly" in response.headers["set-cookie"].lower()


def test_google_login_is_unavailable_when_not_configured(
    auth_settings: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import clear_settings_cache, get_settings
    from app.main import create_app

    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    clear_settings_cache()
    with TestClient(create_app(get_settings()), follow_redirects=False) as client:
        response = client.get("/api/v1/auth/google")
    assert response.status_code == 503
    assert response.json() == {"detail": "Google sign-in is not configured"}


# ----------------------------------------------------------------------------- callback


def test_first_sign_in_creates_a_plain_user_and_lands_on_the_user_portal(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    response = sign_in("chef@example.com")

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/app"
    assert SESSION_COOKIE in response.cookies

    me = auth_client.get("/api/v1/auth/me").json()
    assert me["user"]["email"] == "chef@example.com"
    assert me["user"]["platform_role"] == "user"
    assert me["effective_role"] == "user"
    assert me["portal_path"] == "/app"
    assert me["memberships"] == []


def test_session_cookie_is_httponly_and_lasts_a_month(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    response = sign_in("chef@example.com")

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=2592000" in cookie  # 30 days
    assert "secure" not in cookie  # APP_ENV=test, so plain http development works


def test_signing_in_again_reuses_the_same_account(auth_client: TestClient, sign_in: SignIn) -> None:
    first = sign_in("chef@example.com").status_code
    first_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    auth_client.cookies.clear()
    sign_in("chef@example.com")
    second_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    assert first == 302
    assert first_id == second_id


def test_safe_next_path_wins_over_the_portal(auth_client: TestClient, sign_in: SignIn) -> None:
    response = sign_in("chef@example.com", next_path="/app/settings")
    assert response.headers["location"] == "http://localhost:3000/app/settings"


def test_open_redirect_is_dropped_for_the_portal(auth_client: TestClient, sign_in: SignIn) -> None:
    response = sign_in("chef@example.com", next_path="//evil.example/steal")
    assert response.headers["location"] == "http://localhost:3000/app"


def test_state_mismatch_is_refused(auth_client: TestClient, google: FakeGoogleProvider) -> None:
    auth_client.get("/api/v1/auth/google")
    code = google.issue_code("chef@example.com")

    response = auth_client.get(
        "/api/v1/auth/google/callback", params={"code": code, "state": "not-the-state"}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/login?error=invalid_state"
    assert SESSION_COOKIE not in response.cookies


def test_callback_without_a_started_login_is_refused(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/api/v1/auth/google/callback", params={"code": "whatever", "state": "x"}
    )
    assert response.headers["location"] == "http://localhost:3000/login?error=missing_state"


def test_google_reported_error_goes_back_to_login(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
    assert response.headers["location"] == "http://localhost:3000/login?error=google_declined"


def test_unverified_email_cannot_sign_in(auth_client: TestClient, sign_in: SignIn) -> None:
    response = sign_in("spoofed@example.com", email_verified=False)

    assert response.headers["location"] == "http://localhost:3000/login?error=google_rejected"
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_unknown_code_is_refused(auth_client: TestClient) -> None:
    start = auth_client.get("/api/v1/auth/google")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    response = auth_client.get(
        "/api/v1/auth/google/callback", params={"code": "made-up", "state": state}
    )

    assert response.headers["location"] == "http://localhost:3000/login?error=google_rejected"


# ----------------------------------------------------------------------------- session


def test_me_requires_a_session(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in"}


def test_an_unknown_cookie_is_not_a_session(auth_client: TestClient) -> None:
    auth_client.cookies.set(SESSION_COOKIE, "not-a-real-token")
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_the_session(auth_client: TestClient, sign_in: SignIn) -> None:
    sign_in("chef@example.com")
    token = auth_client.cookies[SESSION_COOKIE]

    logout = auth_client.post("/api/v1/auth/logout")

    assert logout.status_code == 200
    assert logout.json() == {"signed_out": True}
    # Even replaying the old cookie value gets nowhere: the session document is gone.
    auth_client.cookies.set(SESSION_COOKIE, token)
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_logout_without_a_session_still_clears_the_cookie(auth_client: TestClient) -> None:
    response = auth_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"signed_out": False}


# ----------------------------------------------------------------------------- bootstrap admin


def test_bootstrap_address_signs_in_as_platform_admin(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    response = sign_in(ADMIN_EMAIL)

    assert response.headers["location"] == "http://localhost:3000/admin"
    me = auth_client.get("/api/v1/auth/me").json()
    assert me["user"]["platform_role"] == "admin"
    assert me["effective_role"] == "admin"


def test_a_different_google_account_cannot_claim_an_existing_email(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """`google_sub` is the identity key; a matching email never re-binds the account."""
    sign_in("chef@example.com", sub="google-sub-original")
    original_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    auth_client.cookies.clear()

    response = sign_in("chef@example.com", sub="google-sub-impostor")

    assert response.headers["location"] == "http://localhost:3000/login?error=account_conflict"
    auth_client.cookies.clear()
    sign_in("chef@example.com", sub="google-sub-original")
    assert auth_client.get("/api/v1/auth/me").json()["user"]["id"] == original_id
