"""Application settings (pydantic-settings).

Values come from environment variables, falling back to ``.env`` files: the repo-root
``.env`` (resolved relative to this module) first, then ``./.env`` in the current working
directory; environment variables always win and later files override earlier ones. Keys
owned by other layers (``LLM_*``, ``NUXT_*``) are ignored here - the ``agents`` package
reads its own settings from the same file.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

AppEnv = Literal["development", "test", "production"]

REPO_ROOT_ENV_FILE: Path = Path(__file__).resolve().parents[3] / ".env"
"""Repo-root ``.env`` shared with the agents package (``backend/app/core/config.py`` -> root)."""

DEFAULT_CORS_ORIGINS: tuple[str, ...] = ("http://localhost:3000",)

MONGODB_SCHEMES: tuple[str, ...] = ("mongodb://", "mongodb+srv://")
"""Connection-string schemes accepted for ``DATABASE_URL`` (standard and DNS-seedlist)."""

DEFAULT_DATABASE_NAME = "menuhero"

DEFAULT_FRONTEND_BASE_URL = "http://localhost:3000"
"""Where the browser is sent back to after a Google sign-in round trip."""

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GOOGLE_BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
"""The single scope the Business Profile APIs accept. Requested only when someone asks to
import, never at sign-in: it is a management credential, not an identity claim."""

GOOGLE_ACCOUNT_MANAGEMENT_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
"""Account Management API: ``GET /accounts`` lists the Business Profile accounts."""

GOOGLE_BUSINESS_INFORMATION_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
"""Business Information API: ``GET /{account}/locations`` lists a Business's locations."""


class Settings(BaseSettings):
    """Backend configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = Field(default="development", description="APP_ENV")
    secret_key: SecretStr = Field(
        default=SecretStr(""), description="SECRET_KEY; required when APP_ENV=production."
    )
    database_url: str | None = Field(
        default=None,
        description="DATABASE_URL: a MongoDB connection string (optional).",
    )
    mongodb_database: str = Field(
        default=DEFAULT_DATABASE_NAME,
        min_length=1,
        description="MONGODB_DATABASE: database name used when DATABASE_URL carries no path.",
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS),
        description="CORS_ORIGINS: comma-separated origins or a JSON list.",
    )
    log_level: str = Field(default="INFO", description="LOG_LEVEL (standard logging names).")
    api_prefix: str = Field(default="/api", description="Mount point of the HTTP API.")
    project_name: str = Field(default="Menu Hero API", description="OpenAPI title.")

    # --- Google sign-in (management app onboarding) ---
    google_client_id: str = Field(
        default="", description="GOOGLE_CLIENT_ID: OAuth 2.0 web client id."
    )
    google_client_secret: SecretStr = Field(
        default=SecretStr(""), description="GOOGLE_CLIENT_SECRET: OAuth 2.0 web client secret."
    )
    google_redirect_uri: str = Field(
        default=f"{DEFAULT_FRONTEND_BASE_URL}/api/v1/auth/google/callback",
        description=(
            "GOOGLE_REDIRECT_URI: must match a redirect URI registered with Google, and must "
            "share a hostname with FRONTEND_BASE_URL or the session cookie is set on the "
            "wrong origin."
        ),
    )
    google_authorization_endpoint: str = Field(
        default=GOOGLE_AUTHORIZATION_ENDPOINT,
        description="Overridable so tests can point the flow at a local double.",
    )
    google_token_endpoint: str = Field(
        default=GOOGLE_TOKEN_ENDPOINT,
        description="Overridable so tests can point the flow at a local double.",
    )
    google_jwks_uri: str = Field(
        default=GOOGLE_JWKS_URI,
        description="Where the id_token signing keys are fetched from (JWKS).",
    )

    # --- Google Business Profile import (separate grant, same OAuth client) ---
    google_business_redirect_uri: str = Field(
        default=f"{DEFAULT_FRONTEND_BASE_URL}/api/v1/google-business/callback",
        description=(
            "GOOGLE_BUSINESS_REDIRECT_URI: registered with Google alongside the sign-in "
            "one. A separate URI so the two consent round trips cannot be confused."
        ),
    )
    google_account_management_base_url: str = Field(
        default=GOOGLE_ACCOUNT_MANAGEMENT_BASE,
        description="Overridable so tests can point the import at a local double.",
    )
    google_business_information_base_url: str = Field(
        default=GOOGLE_BUSINESS_INFORMATION_BASE,
        description="Overridable so tests can point the import at a local double.",
    )
    google_revoke_endpoint: str = Field(
        default=GOOGLE_REVOKE_ENDPOINT,
        description="Where a refresh token is revoked when someone disconnects.",
    )

    # --- Sessions ---
    frontend_base_url: str = Field(
        default=DEFAULT_FRONTEND_BASE_URL,
        description="FRONTEND_BASE_URL: origin the OAuth callback redirects back to.",
    )
    session_cookie_name: str = Field(
        default="mh_session", min_length=1, description="Name of the session cookie."
    )
    session_ttl_days: int = Field(
        default=30, ge=1, le=365, description="SESSION_TTL_DAYS: how long a session stays valid."
    )
    invite_ttl_days: int = Field(
        default=14, ge=1, le=365, description="INVITE_TTL_DAYS: how long an invite stays pending."
    )
    bootstrap_admin_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "BOOTSTRAP_ADMIN_EMAILS: comma-separated addresses promoted to platform admin "
            "on sign-in. The only way to create the first admin; every later one is granted "
            "through the role-change API."
        ),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        """Accept ``a,b,c`` (comma-separated) or ``["a", "b"]`` (JSON) from the environment."""
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"CORS_ORIGINS is not valid JSON: {exc.msg}") from exc
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS JSON must be a list of origins")
            return [str(origin).strip() for origin in parsed if str(origin).strip()]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @field_validator("bootstrap_admin_emails", mode="before")
    @classmethod
    def _parse_admin_emails(cls, value: Any) -> Any:
        """Accept ``a@x.com,b@x.com``; addresses are lower-cased to match stored users."""
        if not isinstance(value, str):
            return value
        return [email.strip().lower() for email in value.split(",") if email.strip()]

    @field_validator("database_url", mode="before")
    @classmethod
    def _validate_database_url(cls, value: Any) -> Any:
        """Validate the MongoDB connection string, keeping the operator's text verbatim.

        The string is deliberately *not* parsed into a ``MongoDsn``: pydantic normalises a
        URL by adding the default port, and pymongo rejects ``mongodb+srv://`` URIs that
        carry one ("must not include a port number"), which would break every Atlas
        deployment. Validation therefore mirrors the driver's own rules instead.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a string")
        url = value.strip()
        if not url:
            # `DATABASE_URL=` (blank, as in .env.example) means "not configured".
            return None
        scheme = next((s for s in MONGODB_SCHEMES if url.startswith(s)), None)
        if scheme is None:
            raise ValueError(f"DATABASE_URL must start with one of {', '.join(MONGODB_SCHEMES)}")
        host_part = url[len(scheme) :].split("/", 1)[0].split("?", 1)[0]
        _, _, hosts = host_part.rpartition("@")
        if not hosts:
            raise ValueError("DATABASE_URL is missing a host")
        if scheme == "mongodb+srv://" and ":" in hosts:
            raise ValueError("mongodb+srv:// URLs must not include a port number")
        return url

    @field_validator("frontend_base_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, value: Any) -> Any:
        """Keep the origin without a trailing slash so paths concatenate cleanly."""
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: Any) -> Any:
        """Upper-case the level and reject names the logging module does not know."""
        if not isinstance(value, str):
            return value
        level = value.strip().upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"Unknown log level {value!r}")
        return level

    @model_validator(mode="after")
    def _require_secret_in_production(self) -> Settings:
        """A production deployment must never run with an empty secret."""
        if self.app_env == "production" and not self.secret_key.get_secret_value():
            raise ValueError("SECRET_KEY must be set when APP_ENV=production")
        return self

    @property
    def is_production(self) -> bool:
        """True when running with ``APP_ENV=production``."""
        return self.app_env == "production"

    @property
    def oauth_hosts_match(self) -> bool:
        """True when the callback and the frontend share a hostname.

        Cookies are scoped by host and ignore the port, so a callback served from
        ``127.0.0.1`` sets a cookie the page on ``localhost`` will never send back - the
        sign-in then looks like an endless loop. Warned about at start-up.
        """
        return (
            urlsplit(self.google_redirect_uri).hostname == urlsplit(self.frontend_base_url).hostname
        )

    @property
    def google_oauth_configured(self) -> bool:
        """True when both halves of the Google OAuth client credential are present."""
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @property
    def google_business_configured(self) -> bool:
        """True when the Business Profile import can actually run.

        There is deliberately no feature switch: the import is available wherever it *can*
        work, and what it needs is the same OAuth client sign-in already uses plus a
        ``SECRET_KEY``. The key is not optional - the refresh token Google hands back is
        encrypted at rest with a key derived from it (:mod:`app.core.crypto`), so without
        one there is nowhere safe to put the credential the flow returns, and offering the
        button would be a promise the deployment cannot keep.

        Whether Google will actually *answer* is a separate matter: the Business Profile
        APIs are allow-listed per Cloud project, and an unapproved one returns
        ``PERMISSION_DENIED``. That cannot be known without asking, so it surfaces as an
        error on the first listing rather than as a claim made here.
        """
        return self.google_oauth_configured and bool(self.secret_key.get_secret_value())

    @property
    def session_ttl(self) -> timedelta:
        """Session lifetime as a ``timedelta`` (cookie ``Max-Age`` and document expiry)."""
        return timedelta(days=self.session_ttl_days)

    @property
    def invite_ttl(self) -> timedelta:
        """Invite lifetime as a ``timedelta``."""
        return timedelta(days=self.invite_ttl_days)

    @property
    def database_configured(self) -> bool:
        """True when a MongoDB ``DATABASE_URL`` was provided."""
        return self.database_url is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` instance (built on first use)."""
    settings = Settings()
    logger.debug(
        "settings loaded: env=%s api_prefix=%s database=%s cors=%s",
        settings.app_env,
        settings.api_prefix,
        "configured" if settings.database_configured else "not configured",
        settings.cors_origins,
    )
    return settings


def clear_settings_cache() -> None:
    """Drop the cached settings so the next :func:`get_settings` call re-reads the environment."""
    get_settings.cache_clear()
