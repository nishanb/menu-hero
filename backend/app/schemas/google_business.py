"""HTTP schemas of the Google Business Profile import endpoints.

Nothing here can carry a credential: the connection is described by which account it is
for and when it was made, never by the token behind it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import GoogleConnection
from app.models.base import PyObjectId
from app.services.google_business import BusinessAccount, BusinessLocation


class GoogleConnectionOut(BaseModel):
    """The caller's Google Business connection, as the UI needs to describe it."""

    connected: bool = False
    google_email: str = ""
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None

    @classmethod
    def from_connection(cls, connection: GoogleConnection | None) -> GoogleConnectionOut:
        """Describe a connection, or the absence of one."""
        if connection is None:
            return cls()
        return cls(
            connected=True,
            google_email=connection.google_email,
            scopes=connection.scopes,
            connected_at=connection.created_at,
        )


class GoogleBusinessStatusResponse(BaseModel):
    """Body of ``GET /api/v1/google-business/status``.

    ``configured`` is about the deployment, ``connected`` about the person: the import
    screen has to tell "nobody set this up" apart from "you have not connected yet".
    """

    configured: bool = Field(
        description="True when this deployment has the Business Profile import switched on."
    )
    connection: GoogleConnectionOut = Field(default_factory=GoogleConnectionOut)


class BusinessAccountOut(BaseModel):
    """One Google Business Profile account."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    account_name: str = ""
    type: str = ""
    verification_state: str = ""

    @classmethod
    def from_account(cls, account: BusinessAccount) -> BusinessAccountOut:
        """Project the service model."""
        return cls.model_validate(account, from_attributes=True)


class BusinessLocationOut(BaseModel):
    """One Google Business Profile location, plus whether it is already a restaurant here."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    account: str = ""
    title: str = ""
    description: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    maps_url: str = ""
    place_id: str = ""
    store_code: str = ""
    primary_category: str = ""
    imported: bool = Field(
        default=False, description="True when a restaurant here was already imported from it."
    )

    @classmethod
    def from_location(cls, location: BusinessLocation, *, imported: bool) -> BusinessLocationOut:
        """Project the service model, marking what has already been taken."""
        return cls(**location.model_dump(), imported=imported)


class BusinessLocationListResponse(BaseModel):
    """Body of ``GET /api/v1/google-business/locations``."""

    accounts: list[BusinessAccountOut] = Field(default_factory=list)
    locations: list[BusinessLocationOut] = Field(default_factory=list)


class BusinessImportRequest(BaseModel):
    """Body of ``POST /api/v1/google-business/import``.

    Only the resource name travels: the server re-reads the location from Google, so
    nothing the browser sends decides what ends up stored.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [{"location": "locations/12345"}]})

    location: str = Field(
        min_length=1, max_length=200, description="Resource name, e.g. ``locations/12345``."
    )


class BusinessSyncRequest(BaseModel):
    """Body of ``POST /api/v1/google-business/sync``."""

    tenant_id: PyObjectId = Field(description="The imported restaurant to refresh.")
