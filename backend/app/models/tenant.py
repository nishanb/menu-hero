"""Tenants (restaurants), their onboarding profile, and their repository.

The document carries what onboarding collects: who the restaurant is (``name``,
``description``, ``logo``), how to find it (``location_url``), how it trades (``services``,
``diet_options``) and the licence numbers a local operator has to keep on file (``extras``,
e.g. FSSAI and GST). The richer ``profile``/``settings``/``live_version`` structure of HLD
3.8 and 4 belongs to the menu and chat work and is layered on later; this document is the
anchor a membership and an invite point at.

Everything on the profile is *tenant-authored data*, never instructions (HLD trust
boundary), so the validators here are about size and shape only - length caps, a closed
character set for keys, and a hard ceiling on the inline logo.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pymongo import IndexModel

from app.models.base import ASCENDING, MongoDocument, MongoRepository
from app.models.user import utcnow

SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$")
"""3-64 lower-case characters; the tenant's stable, URL-safe handle."""

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 64

OPTION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 -]{0,38}[a-z0-9]$")
"""Shape of a free-form option value (a service, a diet option): 2-40 lower-case chars."""

EXTRA_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,38}[a-z0-9]$")
"""Shape of an ``extras`` key, e.g. ``fssai_licence`` or ``gst_number``."""

MAX_EXTRAS = 25
MAX_EXTRA_VALUE_LENGTH = 200
MAX_OPTIONS = 25

SUGGESTED_SERVICES: tuple[str, ...] = ("dining", "delivery", "takeaway")
"""Offered in the UI. The field is open: a restaurant may add its own."""

SUGGESTED_DIET_OPTIONS: tuple[str, ...] = ("veg", "non-veg", "egg", "vegan", "jain", "halal")
"""Offered in the UI. Deliberately not a closed enum - onboarding must accept new ones."""

LOGO_DATA_URL_PATTERN = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/]+={0,2}$")
"""Inline logo, as a data URL. SVG is excluded on purpose: it can carry script."""

MAX_LOGO_LENGTH = 512_000
"""~375 KB of image. Big enough for a mark, small enough to sit inside a document."""

LOGO_FIELD = "logo"
"""Excluded from list queries: a list of restaurants must not carry a list of images."""

SUMMARY_PROJECTION: dict[str, int] = {LOGO_FIELD: 0}
"""Everything except the inline logo. Used by every endpoint that returns more than one."""


def slugify(value: str) -> str:
    """``Café Móka`` -> ``cafe-moka``; the raw form of a handle, not yet validated.

    The NFKD pass matters: it folds accents onto their base letters, so "Café" becomes
    ``cafe`` rather than ``caf``. It has to stay in step with the same function in
    ``frontend/composables/useRestaurants.ts``, which previews the address under the name
    field while it is being typed - a preview that disagrees with what gets stored is worse
    than no preview.

    Returns ``""`` when nothing usable survives, which the caller turns into a fallback -
    a name written entirely in a non-Latin script is the ordinary case, not an error.
    """
    folded = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    stripped = re.sub(r"[^a-z0-9\s-]", "", ascii_only)
    return re.sub(r"[\s-]+", "-", stripped).strip("-")[:SLUG_MAX_LENGTH].rstrip("-")


class PosSettings(BaseModel):
    """Which parts of the till this restaurant runs.

    ``billing`` is the till proper: the floor plan and its tables, takeaway bills, sending
    rounds and settling. Off, the POS is a kitchen display - the KOT board and nothing
    else - for a restaurant whose orders arrive some other way (the diner's QR menu, once
    live). Kitchen tickets have no switch: an order is a ticket wherever it comes from, and
    a kitchen that cannot see its tickets is not a configuration, it is an outage.
    """

    billing: bool = Field(
        default=True, description="Seat tables, open takeaway bills and settle them on the POS."
    )


class Tenant(MongoDocument):
    """One restaurant."""

    slug: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    location_url: str = Field(
        default="", max_length=2000, description="Google Maps link to the restaurant."
    )
    logo: str = Field(
        default="", max_length=MAX_LOGO_LENGTH, description="Inline image as a data URL."
    )
    services: list[str] = Field(
        default_factory=list, description="How the restaurant trades: dining, delivery, ..."
    )
    diet_options: list[str] = Field(
        default_factory=list, description="Diets catered for: veg, non-veg, and any others."
    )
    extras: dict[str, str] = Field(
        default_factory=dict,
        description="Free-form key/value properties: FSSAI licence, GST number, ...",
    )
    google_location: str | None = Field(
        default=None,
        description="Resource name of the Google Business location this was imported from.",
    )
    pos: PosSettings = Field(default_factory=PosSettings)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def _validate_slug(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        slug = value.strip().lower()
        if not SLUG_PATTERN.match(slug):
            raise ValueError(
                "slug must be 3-64 characters of a-z, 0-9 and '-', starting and ending "
                "with a letter or digit"
            )
        return slug

    @field_validator("location_url", mode="before")
    @classmethod
    def _validate_location_url(cls, value: object) -> object:
        """Only ``https://`` links: the field is rendered as an anchor, so ``javascript:`` is
        a stored-XSS vector and a relative path would point at our own app."""
        if not isinstance(value, str):
            return value
        url = value.strip()
        if url and not url.startswith("https://"):
            raise ValueError("location must be an https:// link")
        return url

    @field_validator("logo", mode="before")
    @classmethod
    def _validate_logo(cls, value: object) -> object:
        """Accept a base64 PNG/JPEG/WEBP data URL, and nothing else."""
        if not isinstance(value, str):
            return value
        logo = value.strip()
        if logo and not LOGO_DATA_URL_PATTERN.match(logo):
            raise ValueError("logo must be a base64 PNG, JPEG or WEBP data URL")
        return logo

    @field_validator("services", "diet_options", mode="before")
    @classmethod
    def _normalise_options(cls, value: object) -> object:
        """Lower-case, de-duplicate and bound an open list of option strings."""
        if not isinstance(value, list):
            return value
        seen: list[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("options must be strings")
            option = re.sub(r"\s+", " ", raw.strip().lower())
            if not option:
                continue
            if not OPTION_PATTERN.match(option):
                raise ValueError(
                    f"'{raw}' is not a usable option: use 2-40 characters of a-z, 0-9, space or '-'"
                )
            if option not in seen:
                seen.append(option)
        if len(seen) > MAX_OPTIONS:
            raise ValueError(f"at most {MAX_OPTIONS} options are allowed")
        return seen

    @field_validator("extras", mode="before")
    @classmethod
    def _normalise_extras(cls, value: object) -> object:
        """Bound the key/value map, and keep keys to a shape that is safe as a BSON field."""
        if not isinstance(value, dict):
            return value
        extras: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip().lower().replace(" ", "_")
            if not key:
                continue
            if not EXTRA_KEY_PATTERN.match(key):
                raise ValueError(
                    f"'{raw_key}' is not a usable property name: use 2-40 characters of "
                    "a-z, 0-9, '_' or '-'"
                )
            text = str(raw_value).strip()
            if len(text) > MAX_EXTRA_VALUE_LENGTH:
                raise ValueError(f"'{key}' is longer than {MAX_EXTRA_VALUE_LENGTH} characters")
            extras[key] = text
        if len(extras) > MAX_EXTRAS:
            raise ValueError(f"at most {MAX_EXTRAS} properties are allowed")
        return extras


class TenantRepository(MongoRepository[Tenant]):
    """``tenants`` - unique on ``slug``."""

    collection_name = "tenants"
    document_type = Tenant

    async def ensure_indexes(self) -> None:
        await self.collection.create_indexes(
            [
                IndexModel([("slug", ASCENDING)], name="uq_slug", unique=True),
                IndexModel(
                    [("google_location", ASCENDING)],
                    name="uq_google_location",
                    unique=True,
                    partialFilterExpression={"google_location": {"$type": "string"}},
                ),
            ]
        )

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Look a tenant up by its handle."""
        return await self.find_one({"slug": slug.strip().lower()})

    async def get_by_google_location(self, location_name: str) -> Tenant | None:
        """The tenant already imported from a Google Business location, if any."""
        return await self.find_one({"google_location": location_name})

    async def find_summaries(
        self, filter: dict[str, Any] | None = None, *, limit: int = 0
    ) -> list[Tenant]:
        """Tenants without their inline logos, sorted by name.

        Anything that returns more than one restaurant goes through here: a switcher with
        five restaurants must not download five embedded images to render five initials.
        """
        cursor = self.collection.find(dict(filter or {}), SUMMARY_PROJECTION, limit=limit).sort(
            [("name", ASCENDING)]
        )
        return [Tenant.from_mongo(raw) async for raw in cursor]


class SlugAllocator:
    """Turns a restaurant name into a free, valid slug.

    Self-serve onboarding asks for a name, not a handle, so the server derives one. The
    derived form collides often ("Spice Garden" is not a rare name), hence the numbered
    suffixes; ``uq_slug`` remains the actual guarantee, and the caller still has to handle
    a :class:`~pymongo.errors.DuplicateKeyError` from a concurrent insert.
    """

    MAX_ATTEMPTS = 50
    FALLBACK = "restaurant"

    def __init__(self, tenants: TenantRepository) -> None:
        self._tenants = tenants

    async def allocate(self, name: str) -> str:
        """Return a slug derived from ``name`` that nothing is using yet."""
        base = slugify(name) or self.FALLBACK
        base = base.ljust(SLUG_MIN_LENGTH, "0")[:SLUG_MAX_LENGTH].rstrip("-")
        if len(base) < SLUG_MIN_LENGTH:
            base = self.FALLBACK
        for attempt in range(self.MAX_ATTEMPTS):
            candidate = base if attempt == 0 else self._suffixed(base, attempt + 1)
            if await self._tenants.get_by_slug(candidate) is None:
                return candidate
        # 50 restaurants share this name; stop guessing and use something unique instead.
        return self._suffixed(base, int(utcnow().timestamp()))

    @staticmethod
    def _suffixed(base: str, number: int) -> str:
        """``spice-garden`` + 2 -> ``spice-garden-2``, trimmed to fit the slug length."""
        suffix = f"-{number}"
        return f"{base[: SLUG_MAX_LENGTH - len(suffix)].rstrip('-')}{suffix}"


__all__ = [
    "LOGO_DATA_URL_PATTERN",
    "MAX_EXTRAS",
    "MAX_EXTRA_VALUE_LENGTH",
    "MAX_LOGO_LENGTH",
    "MAX_OPTIONS",
    "SLUG_PATTERN",
    "SUGGESTED_DIET_OPTIONS",
    "SUGGESTED_SERVICES",
    "SlugAllocator",
    "Tenant",
    "TenantRepository",
    "slugify",
]
