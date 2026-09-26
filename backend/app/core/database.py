"""Optional MongoDB client.

The client is created lazily, and only when ``DATABASE_URL`` is set. Nothing connects at
import or startup time: PyMongo's async client opens sockets in the background on first
use, so a misconfigured or unreachable database never blocks application start-up - it
surfaces as a timeout on the first query instead.

PyMongo's native async API (``AsyncMongoClient``, PyMongo >= 4.13) is used directly;
Motor is deprecated and reached end of life in 2026.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pymongo import AsyncMongoClient
from pymongo import timeout as mongo_timeout
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

Document = dict[str, Any]
"""Raw BSON document type used by the untyped driver handles."""

MongoClient = AsyncMongoClient[Document]
MongoDatabase = AsyncDatabase[Document]

SERVER_SELECTION_TIMEOUT_MS = 5_000
"""How long a query waits for a reachable server before failing (driver default: 30s)."""

_client: MongoClient | None = None


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when database access is requested but ``DATABASE_URL`` is not set."""

    def __init__(self) -> None:
        super().__init__("Database is not configured (DATABASE_URL is not set)")


def is_database_configured(settings: Settings | None = None) -> bool:
    """True when the settings carry a ``DATABASE_URL``."""
    settings = settings if settings is not None else get_settings()
    return settings.database_configured


def redact_credentials(url: str) -> str:
    """Return ``url`` with any password replaced by ``***`` so it is safe to log."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    user = f"{parts.username}:***@" if parts.username else "***@"
    netloc = f"{user}{parts.netloc.rpartition('@')[2]}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def get_client() -> MongoClient:
    """Return the shared :class:`AsyncMongoClient`, creating it on first use.

    Raises :class:`DatabaseNotConfiguredError` when ``DATABASE_URL`` is not set.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if settings.database_url is None:
            raise DatabaseNotConfiguredError
        _client = AsyncMongoClient(
            settings.database_url,
            serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
            tz_aware=True,
            uuidRepresentation="standard",
        )
        logger.info("mongodb client created for %s", redact_credentials(settings.database_url))
    return _client


def get_database() -> MongoDatabase:
    """Return the configured database handle.

    The database name comes from the ``DATABASE_URL`` path when it has one, and from
    ``MONGODB_DATABASE`` otherwise.
    """
    return get_client().get_default_database(default=get_settings().mongodb_database)


async def ping(timeout_ms: int = SERVER_SELECTION_TIMEOUT_MS) -> None:
    """Round-trip a ``ping`` command; raises ``PyMongoError`` when the server is unreachable."""
    with mongo_timeout(timeout_ms / 1000):
        await get_client().admin.command("ping")


async def close_client() -> None:
    """Close the client and forget it (lifespan shutdown, tests).

    An ``AsyncMongoClient`` is bound to the event loop that used it, so the cached client
    must be dropped whenever that loop goes away.
    """
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()
        logger.info("mongodb client closed")
