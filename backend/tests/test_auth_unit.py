"""The pieces of the sign-in flow that need neither a database nor a network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.security import generate_token, hash_token, tokens_match
from app.models.roles import PlatformRole, TenantRole, effective_role, portal_path
from app.services.auth_service import OAuthState, is_safe_next_path
from app.services.google_oauth import GoogleAuthError, identity_from_claims

CLIENT_ID = "client-id.apps.googleusercontent.com"


def _claims(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": (datetime.now(UTC) + timedelta(minutes=5)).timestamp(),
        "sub": "1234567890",
        "email": "chef@example.com",
        "email_verified": True,
        "name": "Chef",
    }
    return base | overrides


# ----------------------------------------------------------------------------- tokens


def test_tokens_are_unique_and_only_stored_as_a_digest() -> None:
    first, second = generate_token(), generate_token()
    assert first != second
    assert hash_token(first) != first
    assert len(hash_token(first)) == 64


def test_tokens_match_compares_against_the_digest() -> None:
    token = generate_token()
    assert tokens_match(token, hash_token(token))
    assert not tokens_match(generate_token(), hash_token(token))


# ----------------------------------------------------------------------------- roles


@pytest.mark.parametrize(
    ("platform_role", "tenant_roles", "expected", "expected_path"),
    [
        (PlatformRole.USER, set(), PlatformRole.USER, "/app"),
        (PlatformRole.USER, {TenantRole.STAFF}, TenantRole.STAFF, "/staff"),
        (PlatformRole.USER, {TenantRole.STAFF, TenantRole.OWNER}, TenantRole.OWNER, "/owner"),
        (PlatformRole.ADMIN, {TenantRole.OWNER}, PlatformRole.ADMIN, "/admin"),
    ],
)
def test_effective_role_takes_the_strongest_and_routes_to_its_portal(
    platform_role: PlatformRole,
    tenant_roles: set[TenantRole],
    expected: PlatformRole | TenantRole,
    expected_path: str,
) -> None:
    role = effective_role(platform_role, tenant_roles)
    assert role is expected
    assert portal_path(role) == expected_path


# ----------------------------------------------------------------------------- oauth state


def test_state_cookie_round_trips_the_next_path() -> None:
    state = OAuthState.create("/owner/menu")
    decoded = OAuthState.decode(state.encode())
    assert decoded.state == state.state
    assert decoded.next_path == "/owner/menu"


def test_state_is_random_per_login() -> None:
    assert OAuthState.create(None).state != OAuthState.create(None).state


def test_malformed_state_cookie_decodes_to_something_that_cannot_match() -> None:
    assert OAuthState.decode("").state == ""


@pytest.mark.parametrize("path", ["/", "/app", "/owner/menu?tab=items"])
def test_safe_next_paths(path: str) -> None:
    assert is_safe_next_path(path)


@pytest.mark.parametrize(
    "path",
    ["//evil.example", "https://evil.example", "http://evil.example", "evil", "/\\evil.example"],
)
def test_unsafe_next_paths_are_refused(path: str) -> None:
    assert not is_safe_next_path(path)


def test_unsafe_next_path_is_dropped_rather_than_carried() -> None:
    assert OAuthState.create("//evil.example").next_path == ""


# ----------------------------------------------------------------------------- id_token claims


def test_valid_claims_become_an_identity() -> None:
    identity = identity_from_claims(_claims(), client_id=CLIENT_ID)
    assert identity.sub == "1234567890"
    assert identity.email == "chef@example.com"
    assert identity.email_verified is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://evil.example"}, "issuer"),
        ({"aud": "someone-elses-client-id"}, "audience"),
        ({"exp": (datetime.now(UTC) - timedelta(hours=1)).timestamp()}, "expiry"),
        ({"email_verified": False}, "unverified email"),
        ({"exp": None}, "missing expiry"),
    ],
)
def test_bad_claims_are_refused(overrides: dict[str, object], reason: str) -> None:
    with pytest.raises(GoogleAuthError):
        identity_from_claims(_claims(**overrides), client_id=CLIENT_ID)


def test_missing_sub_or_email_is_refused() -> None:
    claims = _claims()
    del claims["sub"]
    with pytest.raises(GoogleAuthError):
        identity_from_claims(claims, client_id=CLIENT_ID)


# ----------------------------------------------------------------------------- cookie origin


def test_the_default_callback_and_frontend_share_a_host() -> None:
    """A mismatch would set the session cookie on a host the frontend never sends back."""
    assert Settings(_env_file=None).oauth_hosts_match


def test_a_host_mismatch_is_detected() -> None:
    settings = Settings(
        _env_file=None,
        google_redirect_uri="http://127.0.0.1:8000/api/v1/auth/google/callback",
        frontend_base_url="http://localhost:3000",
    )
    assert not settings.oauth_hosts_match


def test_the_frontend_base_url_keeps_no_trailing_slash() -> None:
    assert Settings(_env_file=None, frontend_base_url="http://x.example/").frontend_base_url == (
        "http://x.example"
    )
