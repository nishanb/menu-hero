"""Dependency provider for the MongoDB database handle (only when ``DATABASE_URL`` is set)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.database import DatabaseNotConfiguredError, MongoDatabase, get_database


def get_db() -> MongoDatabase:
    """Return the database handle; answer 503 when the database is not configured."""
    try:
        return get_database()
    except DatabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
        ) from exc


Db = Annotated[MongoDatabase, Depends(get_db)]
"""Route parameter annotation: ``db: Db``."""
