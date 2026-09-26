"""Settings parsing rules (environment only; .env files are disabled with _env_file=None)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT_ENV_FILE, Settings, clear_settings_cache, get_settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.secret_key.get_secret_value() == ""
    assert settings.database_url is None
    assert settings.database_configured is False
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.log_level == "INFO"
    assert settings.api_prefix == "/api"
    assert settings.project_name == "Menu Hero API"


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:3000, https://menuhero.example ,")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:3000", "https://menuhero.example"]


def test_cors_origins_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.example", "http://b.example"]')
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://a.example", "http://b.example"]


def test_cors_origins_empty_means_none_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert Settings(_env_file=None).cors_origins == []


def test_cors_origins_invalid_json_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["unterminated')
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(_env_file=None)


def test_production_requires_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY must be set"):
        Settings(_env_file=None)


def test_production_with_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "s3cret")
    settings = Settings(_env_file=None)
    assert settings.is_production
    assert settings.secret_key.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)


def test_development_allows_empty_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "")
    assert Settings(_env_file=None).secret_key.get_secret_value() == ""


def test_invalid_app_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_blank_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert Settings(_env_file=None).database_url is None


@pytest.mark.parametrize(
    "url",
    [
        "mongodb://localhost:27017/menuhero",
        "mongodb://menuhero:pw@mongo:27017/menuhero?authSource=admin",
        "mongodb://h1:27017,h2:27017/menuhero?replicaSet=rs0",
        "mongodb+srv://user:pw@cluster0.abcd.mongodb.net/menuhero?retryWrites=true",
        "mongodb://localhost:27017",
    ],
)
def test_database_url_accepts_mongodb(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The string is kept verbatim - the driver, not pydantic, owns the connection string."""
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_configured
    assert settings.database_url == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://menuhero:pw@localhost:5432/menuhero",
        "mysql://user:pw@localhost/db",
        "redis://localhost:6379",
        "mongodb://",
        # pymongo rejects a port on a DNS-seedlist URL, so it must never reach the driver.
        "mongodb+srv://user:pw@cluster0.abcd.mongodb.net:27017/menuhero",
    ],
)
def test_database_url_must_be_mongodb(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_mongodb_database_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).mongodb_database == "menuhero"
    monkeypatch.setenv("MONGODB_DATABASE", "other")
    assert Settings(_env_file=None).mongodb_database == "other"


def test_log_level_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings(_env_file=None).log_level == "DEBUG"


def test_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError, match="Unknown log level"):
        Settings(_env_file=None)


def test_unknown_env_keys_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "not-ours")
    monkeypatch.setenv("NUXT_PUBLIC_API_BASE", "/api")
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "llm_api_key")


def test_get_settings_is_cached_until_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    clear_settings_cache()
    first = get_settings()
    assert first.log_level == "WARNING"
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert get_settings() is first
    clear_settings_cache()
    assert get_settings().log_level == "ERROR"


def test_repo_root_env_file_location() -> None:
    assert REPO_ROOT_ENV_FILE.name == ".env"
    assert (REPO_ROOT_ENV_FILE.parent / "backend" / "app" / "core" / "config.py").is_file()
    assert (REPO_ROOT_ENV_FILE.parent / "agents").is_dir()
