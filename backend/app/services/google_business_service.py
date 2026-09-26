"""Connecting a Google account, listing its businesses, and importing one as a restaurant.

    connect  -> consent URL + state cookie
    callback -> refresh token, encrypted, stored against the person
    browse   -> accounts -> locations, each marked with whether it is already imported
    import   -> a new restaurant owned by the caller, or an update of one they already own

The grant belongs to the *person*, not to a restaurant: it is what lets us read their
Business Profile, and it is deleted the moment they disconnect. Nothing here ever returns
the refresh token, and :class:`~app.core.crypto.TokenCipher` keeps it unreadable in a
database dump.

Google is reached only through :class:`~app.services.google_business.GoogleBusinessProvider`,
so a test substitutes a double exactly as the sign-in tests do.
"""

from __future__ import annotations

import logging

from bson import ObjectId

from app.core.config import Settings
from app.core.crypto import MissingSecretKeyError, TokenCipher
from app.core.database import MongoDatabase
from app.models import (
    GoogleConnection,
    GoogleConnectionRepository,
    Tenant,
    TenantRepository,
    utcnow,
)
from app.services.auth_service import AuthContext
from app.services.google_business import (
    BusinessAccount,
    BusinessLocation,
    GoogleBusinessError,
    GoogleBusinessNotConnectedError,
    GoogleBusinessProvider,
)
from app.services.management_service import ManagementService

logger = logging.getLogger(__name__)

MAX_ACCOUNTS_BROWSED = 20
"""A person with more Business Profile accounts than this picks one explicitly instead of
having every account's locations fetched on page load."""


class GoogleBusinessService:
    """Use-case layer for the ``/google-business`` endpoints."""

    def __init__(
        self,
        database: MongoDatabase,
        *,
        settings: Settings,
        provider: GoogleBusinessProvider,
        management: ManagementService,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._management = management
        self._connections = GoogleConnectionRepository(database)
        self._tenants = TenantRepository(database)

    # ------------------------------------------------------------------ the grant

    def _cipher(self) -> TokenCipher:
        """The cipher protecting refresh tokens at rest."""
        try:
            return TokenCipher(self._settings.secret_key.get_secret_value())
        except MissingSecretKeyError as exc:
            # `google_business_configured` already refuses the flow without a SECRET_KEY, so
            # reaching here means configuration changed under a live request.
            raise GoogleBusinessError(
                "This deployment cannot store Google credentials", code="not_configured"
            ) from exc

    def authorization_url(self, *, state: str) -> str:
        """Consent URL for the business scope."""
        return self._provider.authorization_url(state=state)

    async def store_grant(self, *, code: str, context: AuthContext) -> GoogleConnection:
        """Finish the consent round trip and keep the refresh token for this person."""
        tokens = await self._provider.exchange_code(code)
        connection = GoogleConnection(
            user_id=context.user_id,
            refresh_token_encrypted=self._cipher().encrypt(tokens.refresh_token),
            scopes=list(tokens.scopes),
            google_email=tokens.email,
            updated_at=utcnow(),
        )
        await self._connections.upsert(connection)
        logger.info("google business connected: user=%s", context.user.email)
        return connection

    async def connection_for(self, context: AuthContext) -> GoogleConnection | None:
        """The caller's connection, or ``None``."""
        return await self._connections.get_for_user(context.user_id)

    async def disconnect(self, context: AuthContext) -> bool:
        """Revoke the grant at Google and forget it locally."""
        connection = await self._connections.get_for_user(context.user_id)
        if connection is None:
            return False
        refresh_token = self._cipher().decrypt(connection.refresh_token_encrypted)
        if refresh_token:
            await self._provider.revoke(refresh_token)
        removed = await self._connections.remove_for_user(context.user_id)
        logger.info("google business disconnected: user=%s", context.user.email)
        return removed

    async def _access_token(self, context: AuthContext) -> str:
        """A fresh access token for the caller, or a "connect again" error."""
        connection = await self._connections.get_for_user(context.user_id)
        if connection is None:
            raise GoogleBusinessNotConnectedError()
        refresh_token = self._cipher().decrypt(connection.refresh_token_encrypted)
        if refresh_token is None:
            # Almost always a rotated SECRET_KEY. The stored value is unusable either way,
            # so drop it: leaving it makes the UI claim a connection that cannot work.
            await self._connections.remove_for_user(context.user_id)
            raise GoogleBusinessNotConnectedError(
                "That Google connection can no longer be read. Connect the account again."
            )
        token = await self._provider.access_token(refresh_token)
        await self._connections.touch(context.user_id)
        return token

    # ------------------------------------------------------------------ browsing

    async def list_accounts(self, context: AuthContext) -> list[BusinessAccount]:
        """The Business Profile accounts the caller administers."""
        return await self._provider.list_accounts(await self._access_token(context))

    async def list_locations(
        self, context: AuthContext, *, account: str | None = None
    ) -> tuple[list[BusinessAccount], list[BusinessLocation]]:
        """Accounts and their locations, for the picker.

        With no ``account`` this walks every account the person has, which is what makes the
        screen usable for the overwhelmingly common case of a single Business Profile
        account. One account that fails does not sink the others: a business group the
        person can list but not read is a real configuration, and it should cost that group
        alone, not the whole page.
        """
        access_token = await self._access_token(context)
        accounts = await self._provider.list_accounts(access_token)
        if account is not None:
            accounts = [item for item in accounts if item.name == account]
            if not accounts:
                raise GoogleBusinessError("That Google Business account is not available")

        locations: list[BusinessLocation] = []
        for item in accounts[:MAX_ACCOUNTS_BROWSED]:
            try:
                locations.extend(
                    await self._provider.list_locations(access_token, account=item.name)
                )
            except GoogleBusinessNotConnectedError:
                raise
            except GoogleBusinessError as exc:
                logger.warning("skipping google account %s: %s", item.name, exc)
        return accounts, locations

    async def imported_locations(self) -> set[str]:
        """Resource names of the locations that already back a restaurant."""
        tenants = await self._tenants.find_summaries({"google_location": {"$type": "string"}})
        return {tenant.google_location for tenant in tenants if tenant.google_location}

    # ------------------------------------------------------------------ importing

    async def import_location(self, *, location_name: str, context: AuthContext) -> Tenant:
        """Create a restaurant from one Google Business location.

        The location is re-fetched from Google rather than trusted from the request body:
        the client only names which one, so nothing a browser sends decides what is stored.
        """
        location = await self._find_location(location_name, context)
        existing = await self._tenants.get_by_google_location(location.name)
        if existing is not None:
            raise GoogleBusinessError(
                f"'{existing.name}' has already been imported from this Google location",
                code="already_imported",
            )
        return await self._management.create_restaurant(
            name=location.title or location.store_code or "Restaurant",
            actor=context,
            profile=profile_from_location(location),
            google_location=location.name,
        )

    async def sync_location(self, *, tenant_id: ObjectId, context: AuthContext) -> Tenant:
        """Refresh an imported restaurant from its Google Business location."""
        self._management.assert_can_manage_tenant(context, tenant_id)
        tenant = await self._management.get_tenant(tenant_id)
        if not tenant.google_location:
            raise GoogleBusinessError(
                "This restaurant was not imported from Google Business", code="not_imported"
            )
        location = await self._find_location(tenant.google_location, context)
        return await self._management.update_restaurant(
            tenant_id=tenant_id,
            changes=profile_from_location(location) | {"name": location.title or tenant.name},
            actor=context,
        )

    async def _find_location(self, location_name: str, context: AuthContext) -> BusinessLocation:
        """Fetch one location by resource name, proving the caller can actually see it."""
        _, locations = await self.list_locations(context)
        match = next((item for item in locations if item.name == location_name), None)
        if match is None:
            raise GoogleBusinessError(
                "That location is not in this Google account any more", code="location_not_found"
            )
        return match


def profile_from_location(location: BusinessLocation) -> dict[str, object]:
    """Map a Google Business location onto the restaurant fields onboarding collects.

    Only what Google actually knows is carried across. ``services`` and ``diet_options`` are
    left empty on purpose - Google's business categories say nothing reliable about whether
    a kitchen delivers or cooks vegan, and a wrong default is worse than an empty field the
    owner fills in on the next screen.
    """
    extras = {
        key: value
        for key, value in (
            ("address", location.address),
            ("phone", location.phone),
            ("website", location.website),
            ("google_category", location.primary_category),
            ("google_place_id", location.place_id),
            ("google_store_code", location.store_code),
        )
        if value
    }
    return {
        "description": location.description[:2000],
        "location_url": location.maps_url,
        "extras": extras,
    }
