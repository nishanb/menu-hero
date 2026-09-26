"""The Google client's token exchange and ``id_token`` verification.

These exercise the real code path end to end - token POST, JWKS fetch, signature check,
claim validation - against a fake Google served by an ``httpx.MockTransport``. Signing
keys are generated per test, so a token signed by the wrong key is a real forgery attempt
rather than a mocked-out assertion.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey

from app.core.config import Settings
from app.services.google_oauth import GoogleAuthError, GoogleOAuthClient, reset_jwks_cache

CLIENT_ID = "client-id.apps.googleusercontent.com"
TOKEN_ENDPOINT = "https://token.google.test/token"
JWKS_URI = "https://keys.google.test/certs"
AUTHORIZATION_ENDPOINT = "https://accounts.google.test/authorize"


@pytest.fixture(autouse=True)
def _clear_jwks_cache() -> Iterator[None]:
    """The signing-key cache is module-level; no test may inherit another's keys."""
    reset_jwks_cache()
    yield
    reset_jwks_cache()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        google_client_id=CLIENT_ID,
        google_client_secret="secret",
        google_redirect_uri="http://localhost:3000/api/v1/auth/google/callback",
        google_authorization_endpoint=AUTHORIZATION_ENDPOINT,
        google_token_endpoint=TOKEN_ENDPOINT,
        google_jwks_uri=JWKS_URI,
    )


def _new_key(kid: str = "k1") -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig"}, private=True)


def _public_jwks(*keys: RSAKey) -> dict[str, Any]:
    return {"keys": [key.as_dict(private=False) for key in keys]}


def _claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "sub": "1234567890",
        "email": "chef@example.com",
        "email_verified": True,
        "name": "Chef",
        "picture": "https://pics.example/chef.png",
    }
    return base | overrides


def _sign(key: RSAKey | OctKey, claims: dict[str, Any], *, alg: str = "RS256") -> str:
    header: dict[str, Any] = {"alg": alg}
    kid = key.kid if isinstance(key, RSAKey) else None
    if kid:
        header["kid"] = kid
    return jwt.encode(header, claims, key)


def install_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.AsyncBaseTransport) -> None:
    """Route the module's HTTP calls through ``transport``.

    The module under test calls ``httpx.AsyncClient(...)`` by attribute, so patching the
    class on the httpx module reaches it. The real class has to be captured first -
    otherwise the replacement ends up calling itself.
    """
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


class FakeGoogle:
    """Serves the token endpoint and the JWKS endpoint, and counts the key fetches."""

    def __init__(self, id_token: str, jwks: dict[str, Any]) -> None:
        self.id_token = id_token
        self.jwks = jwks
        self.jwks_requests = 0
        self.token_status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == JWKS_URI:
            self.jwks_requests += 1
            return httpx.Response(200, json=self.jwks)
        if str(request.url) == TOKEN_ENDPOINT:
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token, "token_type": "Bearer"})
        return httpx.Response(404)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make every ``httpx.AsyncClient`` the module builds talk to this fake."""
        install_transport(monkeypatch, httpx.MockTransport(self.handle))


def _google(
    monkeypatch: pytest.MonkeyPatch, id_token: str, jwks: dict[str, Any]
) -> tuple[GoogleOAuthClient, FakeGoogle]:
    fake = FakeGoogle(id_token, jwks)
    fake.install(monkeypatch)
    return GoogleOAuthClient(_settings()), fake


# ----------------------------------------------------------------------------- happy path


async def test_a_properly_signed_token_yields_the_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _new_key()
    client, _ = _google(monkeypatch, _sign(key, _claims()), _public_jwks(key))

    identity = await client.exchange_code("auth-code")

    assert identity.sub == "1234567890"
    assert identity.email == "chef@example.com"
    assert identity.email_verified is True
    assert identity.name == "Chef"
    assert identity.picture == "https://pics.example/chef.png"


def test_the_authorization_url_is_built_by_authlib() -> None:
    url = GoogleOAuthClient(_settings()).authorization_url(state="abc123")

    assert url.startswith(f"{AUTHORIZATION_ENDPOINT}?")
    assert "client_id=client-id.apps.googleusercontent.com" in url
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url
    assert "state=abc123" in url
    assert "prompt=select_account" in url
    assert "client_secret" not in url  # the secret never travels through the browser


# ----------------------------------------------------------------------------- forgery


async def test_a_token_signed_by_another_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of verifying signatures: Google's keys are the only ones that count."""
    forger = _new_key()
    google_key = _new_key()
    client, _ = _google(monkeypatch, _sign(forger, _claims()), _public_jwks(google_key))

    with pytest.raises(GoogleAuthError, match="signature could not be verified"):
        await client.exchange_code("auth-code")


async def test_a_tampered_payload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _new_key()
    header, payload, signature = _sign(key, _claims()).split(".")
    forged_payload = _sign(key, _claims(email="attacker@evil.example")).split(".")[1]
    client, _ = _google(monkeypatch, f"{header}.{forged_payload}.{signature}", _public_jwks(key))

    with pytest.raises(GoogleAuthError, match="signature could not be verified"):
        await client.exchange_code("auth-code")


async def test_a_symmetric_algorithm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Algorithm confusion: only the pinned asymmetric algorithms may verify a token."""
    key = _new_key()
    hmac_key = OctKey.import_key("not-googles-private-key")
    client, _ = _google(monkeypatch, _sign(hmac_key, _claims(), alg="HS256"), _public_jwks(key))

    with pytest.raises(GoogleAuthError, match="signature could not be verified"):
        await client.exchange_code("auth-code")


async def test_garbage_is_not_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _new_key()
    client, _ = _google(monkeypatch, "not-a-jwt", _public_jwks(key))

    with pytest.raises(GoogleAuthError):
        await client.exchange_code("auth-code")


# ----------------------------------------------------------------------------- claims


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"iss": "https://evil.example"}, "id_token rejected"),
        ({"aud": "someone-elses-client-id"}, "id_token rejected"),
        ({"exp": int(time.time()) - 3600}, "id_token rejected"),
        ({"email_verified": False}, "verified email"),
    ],
)
async def test_bad_claims_are_rejected_even_with_a_valid_signature(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], expected: str
) -> None:
    key = _new_key()
    client, _ = _google(monkeypatch, _sign(key, _claims(**overrides)), _public_jwks(key))

    with pytest.raises(GoogleAuthError, match=expected):
        await client.exchange_code("auth-code")


# ----------------------------------------------------------------------------- key handling


async def test_the_signing_keys_are_fetched_once_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _new_key()
    client, fake = _google(monkeypatch, _sign(key, _claims()), _public_jwks(key))

    await client.exchange_code("auth-code")
    await client.exchange_code("auth-code")

    assert fake.jwks_requests == 1


async def test_a_rotated_key_is_picked_up_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached key set that predates a rotation must not lock everyone out."""
    old_key = _new_key("old")
    new_key = _new_key("new")
    client, fake = _google(monkeypatch, _sign(old_key, _claims()), _public_jwks(old_key))
    await client.exchange_code("auth-code")  # warms the cache with the old key

    fake.jwks = _public_jwks(new_key)
    fake.id_token = _sign(new_key, _claims())
    identity = await client.exchange_code("auth-code")

    assert identity.sub == "1234567890"
    assert fake.jwks_requests == 2  # one cold fetch, one refresh after the failed verify


# ----------------------------------------------------------------------------- transport


async def test_a_refused_code_does_not_leak_googles_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _new_key()
    client, fake = _google(monkeypatch, _sign(key, _claims()), _public_jwks(key))
    fake.token_status = 400

    with pytest.raises(GoogleAuthError, match="Google rejected the authorization code"):
        await client.exchange_code("bad-code")


async def test_unreachable_keys_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _new_key()

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == JWKS_URI:
            raise httpx.ConnectError("no route to host")
        return httpx.Response(200, json={"id_token": _sign(key, _claims())})

    install_transport(monkeypatch, httpx.MockTransport(handle))

    with pytest.raises(GoogleAuthError, match="Could not fetch Google's signing keys"):
        await GoogleOAuthClient(_settings()).exchange_code("auth-code")
