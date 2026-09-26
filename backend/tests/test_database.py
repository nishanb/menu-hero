"""Optional database wiring: nothing connects, and the dependency answers 503 when unset."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from pymongo import AsyncMongoClient

from app.core import database
from app.core.config import clear_settings_cache
from app.dependencies.database import get_db

# Port 9 (discard) is never listening: proves client creation does not connect.
UNREACHABLE_URL = "mongodb://menuhero:pw@127.0.0.1:9/menuhero"


@pytest.fixture(autouse=True)
async def _fresh_client() -> AsyncIterator[None]:
    """An AsyncMongoClient is bound to one event loop; never leak it across tests."""
    await database.close_client()
    yield
    await database.close_client()


async def test_not_configured_by_default() -> None:
    assert database.is_database_configured() is False
    with pytest.raises(database.DatabaseNotConfiguredError):
        database.get_client()
    with pytest.raises(database.DatabaseNotConfiguredError):
        database.get_database()


async def test_dependency_returns_503_when_not_configured() -> None:
    with pytest.raises(HTTPException) as excinfo:
        get_db()
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Database is not configured"


async def test_client_created_lazily_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    clear_settings_cache()

    assert database.is_database_configured() is True
    client = database.get_client()
    assert isinstance(client, AsyncMongoClient)
    assert client is database.get_client()  # cached

    await database.close_client()
    assert database.get_client() is not client


async def test_database_name_from_url_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mongodb://127.0.0.1:9/fromurl")
    monkeypatch.setenv("MONGODB_DATABASE", "fromsetting")
    clear_settings_cache()
    assert database.get_database().name == "fromurl"


async def test_database_name_falls_back_to_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL without a path is exactly why MONGODB_DATABASE exists."""
    monkeypatch.setenv("DATABASE_URL", "mongodb://127.0.0.1:9")
    monkeypatch.setenv("MONGODB_DATABASE", "fromsetting")
    clear_settings_cache()
    assert database.get_database().name == "fromsetting"


async def test_database_name_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mongodb://127.0.0.1:9")
    clear_settings_cache()
    assert database.get_database().name == "menuhero"


async def test_dependency_returns_handle_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    clear_settings_cache()
    assert get_db().name == "menuhero"


async def test_ping_fails_fast_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pymongo.errors import PyMongoError

    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    clear_settings_cache()
    with pytest.raises(PyMongoError):
        await database.ping(timeout_ms=200)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("mongodb://user:secret@host:27017/db", "mongodb://user:***@host:27017/db"),
        ("mongodb+srv://u:p@cluster.mongodb.net/db", "mongodb+srv://u:***@cluster.mongodb.net/db"),
        ("mongodb://host:27017/db", "mongodb://host:27017/db"),
    ],
)
def test_redact_credentials(url: str, expected: str) -> None:
    assert database.redact_credentials(url) == expected
