"""Sign-in, sessions and the request's authorisation context.

Layering::

    route -> AuthService -> repositories (users, sessions, memberships, invites)
                         -> GoogleIdentityProvider

The service owns the whole onboarding flow: build the consent URL, validate the callback,
turn a Google identity into a user, consume any invites addressed to that verified email,
open a session, and say which portal the browser should land on. Routes only move cookies.

Two rules shape the design:

* **Everyone starts as ``user``.** A first sign-in creates a user with no memberships;
  ``owner``/``staff`` only ever arrive through an invite or an admin, never from Google.
* **Sessions store nothing but ``user_id``.** Roles are read from the database on every
  request, so a role change or a deactivation is in force immediately - which a month-long
  signed token could not offer.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.database import MongoDatabase
from app.core.security import generate_token, hash_token
from app.models import (
    Invite,
    InviteRepository,
    Membership,
    MembershipRepository,
    PlatformRole,
    Role,
    Session,
    SessionRepository,
    TenantRole,
    User,
    UserRepository,
    effective_role,
    portal_path,
    utcnow,
)
from app.services.google_oauth import GoogleAuthError, GoogleIdentity, GoogleIdentityProvider

logger = logging.getLogger(__name__)

STATE_SEPARATOR = "|"
"""Splits the CSRF state from the post-login path inside the temporary state cookie."""

STATE_TOKEN_BYTES = 16


class AuthError(RuntimeError):
    """The sign-in attempt cannot be completed (bad state, refused account, ...)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        """Short machine-readable reason, safe to put in a redirect query string."""


def is_safe_next_path(path: str) -> bool:
    """True for a same-origin path we are willing to redirect to after sign-in.

    Only relative paths: ``//evil.example`` and ``https://evil.example`` are browser-valid
    redirect targets, so anything but a single leading slash is refused - that is the whole
    of the open-redirect defence.
    """
    return (
        path.startswith("/")
        and not path.startswith("//")
        and "\\" not in path
        and all(char.isprintable() for char in path)
    )


@dataclass(frozen=True, slots=True)
class OAuthState:
    """Contents of the short-lived state cookie set before the redirect to Google."""

    state: str
    next_path: str = ""

    @classmethod
    def create(cls, next_path: str | None) -> OAuthState:
        """Mint a fresh state, keeping ``next_path`` only when it is safe to return to."""
        safe = next_path if next_path and is_safe_next_path(next_path) else ""
        return cls(state=secrets.token_urlsafe(STATE_TOKEN_BYTES), next_path=safe)

    def encode(self) -> str:
        """Cookie value."""
        return f"{self.state}{STATE_SEPARATOR}{self.next_path}"

    @classmethod
    def decode(cls, raw: str) -> OAuthState:
        """Parse a cookie value; a malformed one yields an empty, never-matching state."""
        state, _, next_path = raw.partition(STATE_SEPARATOR)
        return cls(state=state, next_path=next_path)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Who is making the request, and what they may do.

    Built fresh per request from the session cookie; route guards read it and never touch
    the repositories themselves.
    """

    user: User
    session: Session
    memberships: tuple[Membership, ...]

    @property
    def user_id(self) -> ObjectId:
        """The signed-in user's ``_id`` (a persisted user always has one)."""
        assert self.user.id is not None
        return self.user.id

    @property
    def is_platform_admin(self) -> bool:
        """True for the operator role that may manage every tenant and every user."""
        return self.user.platform_role is PlatformRole.ADMIN

    def role_at(self, tenant_id: ObjectId) -> TenantRole | None:
        """The role held at ``tenant_id``, or ``None`` when the person is not a member."""
        return next((m.role for m in self.memberships if m.tenant_id == tenant_id), None)

    @property
    def effective_role(self) -> Role:
        """Strongest role held, across both scopes."""
        return effective_role(self.user.platform_role, {m.role for m in self.memberships})

    @property
    def portal_path(self) -> str:
        """Frontend path this person is sent to after sign-in."""
        return portal_path(self.effective_role)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Everything the callback route needs to finish the round trip."""

    session_token: str
    expires_at: datetime
    context: AuthContext
    redirect_path: str
    """Where to send the browser: the requested ``next`` when safe, else the role's portal."""


class AuthService:
    """Use-case layer for sign-in, sessions and the per-request auth context."""

    def __init__(
        self,
        database: MongoDatabase,
        *,
        settings: Settings,
        identity_provider: GoogleIdentityProvider,
    ) -> None:
        self._settings = settings
        self._google = identity_provider
        self._users = UserRepository(database)
        self._sessions = SessionRepository(database)
        self._memberships = MembershipRepository(database)
        self._invites = InviteRepository(database)

    # ------------------------------------------------------------------ sign-in

    def start_login(self, next_path: str | None = None) -> tuple[str, OAuthState]:
        """Return the Google consent URL and the state to store in a cookie."""
        state = OAuthState.create(next_path)
        return self._google.authorization_url(state=state.state), state

    async def complete_login(
        self, *, code: str, state: str, state_cookie: str | None, user_agent: str = ""
    ) -> LoginResult:
        """Validate the callback, sign the person in, and open a session.

        Raises :class:`AuthError` with a ``code`` the route turns into a query string.
        """
        if not state_cookie:
            raise AuthError("No sign-in was started from this browser", code="missing_state")
        expected = OAuthState.decode(state_cookie)
        if not expected.state or not secrets.compare_digest(expected.state, state):
            raise AuthError("Sign-in state did not match", code="invalid_state")

        try:
            identity = await self._google.exchange_code(code)
        except GoogleAuthError as exc:
            logger.warning("google sign-in refused: %s", exc)
            raise AuthError(str(exc), code="google_rejected") from exc

        user = await self._upsert_user(identity)
        if not user.is_active:
            raise AuthError("This account has been disabled", code="account_disabled")

        await self._consume_invites(user)
        session, token = await self._open_session(user, user_agent=user_agent)
        context = await self.context_for(user, session)
        redirect = expected.next_path or context.portal_path
        logger.info(
            "sign-in completed: user=%s role=%s portal=%s",
            user.email,
            context.effective_role,
            redirect,
        )
        return LoginResult(
            session_token=token,
            expires_at=session.expires_at,
            context=context,
            redirect_path=redirect,
        )

    async def _upsert_user(self, identity: GoogleIdentity) -> User:
        """Find or create the user behind a verified Google identity.

        Lookup is by Google subject only - it is the sole identity key, and it survives an
        email change on the account. A *different* subject arriving with an email that is
        already taken is refused rather than re-bound onto the existing record: a silent
        re-bind is an account takeover primitive, and the case it would cover (a Workspace
        account deleted and recreated under the same address) is rare enough to be worth an
        operator's attention. An invited person needs none of this - invites are matched by
        email after the user exists.
        """
        now = utcnow()
        existing = await self._users.get_by_google_sub(identity.sub)
        if existing is not None:
            assert existing.id is not None
            updated = await self._users.update_by_id(
                existing.id,
                {
                    "email": identity.email.lower(),
                    "name": identity.name or existing.name,
                    "picture": identity.picture or existing.picture,
                    "last_login_at": now,
                },
            )
            user = updated if updated is not None else existing
        else:
            user = User(
                email=identity.email,
                google_sub=identity.sub,
                name=identity.name,
                picture=identity.picture,
                platform_role=PlatformRole.USER,  # everyone starts here
                created_at=now,
                last_login_at=now,
            )
            try:
                user.id = await self._users.insert(user)
            except DuplicateKeyError as exc:
                logger.warning("sign-in refused: %s is bound to another Google account", user.email)
                raise AuthError(
                    "That email address is already linked to a different Google account",
                    code="account_conflict",
                ) from exc
            logger.info("new user registered: %s", user.email)
        return await self._apply_bootstrap_admin(user)

    async def _apply_bootstrap_admin(self, user: User) -> User:
        """Promote a configured bootstrap address to admin, so a first admin can exist.

        The environment variable is a *standing* grant, reapplied at every sign-in: it is
        the break-glass path back in, so a demotion through the API does not survive the
        next sign-in for these addresses. Revoke by removing the address from the
        environment. It only ever promotes - it never demotes anyone.
        """
        if user.platform_role is PlatformRole.ADMIN:
            return user
        if user.email.lower() not in self._settings.bootstrap_admin_emails:
            return user
        assert user.id is not None
        promoted = await self._users.update_by_id(user.id, {"platform_role": PlatformRole.ADMIN})
        logger.info("bootstrap admin applied: %s", user.email)
        return promoted if promoted is not None else user

    async def _consume_invites(self, user: User) -> None:
        """Turn every pending invite for this verified email into a membership."""
        assert user.id is not None
        for invite in await self._invites.list_pending_for_email(user.email):
            await self._accept_invite(invite, user.id)

    async def _accept_invite(self, invite: Invite, user_id: ObjectId) -> Membership:
        """Create (or upgrade) the membership an invite promises and close the invite out."""
        assert invite.id is not None
        existing = await self._memberships.get_for(invite.tenant_id, user_id)
        if existing is None:
            membership = Membership(
                tenant_id=invite.tenant_id,
                user_id=user_id,
                role=invite.role,
                invited_by=invite.invited_by,
            )
            membership.id = await self._memberships.insert(membership)
        elif existing.role is not invite.role:
            assert existing.id is not None
            updated = await self._memberships.update_by_id(existing.id, {"role": invite.role})
            membership = updated if updated is not None else existing
        else:
            membership = existing
        await self._invites.mark_accepted(invite.id, user_id)
        logger.info("invite accepted: tenant=%s role=%s", invite.tenant_id, invite.role)
        return membership

    async def accept_invite_token(self, token: str, user: User) -> Membership:
        """Accept an invite by its token, for a person who is already signed in.

        The invited address must be the one the signed-in account proved to Google, so a
        leaked link cannot hand a role to whoever opens it.
        """
        assert user.id is not None
        invite = await self._invites.get_by_token_hash(hash_token(token))
        if invite is None or not invite.is_pending:
            raise AuthError("This invite is not valid any more", code="invalid_invite")
        if invite.email.lower() != user.email.lower():
            raise AuthError("This invite was sent to a different address", code="invite_mismatch")
        return await self._accept_invite(invite, user.id)

    # ------------------------------------------------------------------ sessions

    async def _open_session(self, user: User, *, user_agent: str) -> tuple[Session, str]:
        """Create a session document and return it with the plaintext cookie token."""
        assert user.id is not None
        token = generate_token()
        now = utcnow()
        session = Session(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + self._settings.session_ttl,
            last_seen_at=now,
            user_agent=user_agent[:256],
        )
        session.id = await self._sessions.insert(session)
        return session, token

    async def resolve_session(self, token: str) -> AuthContext | None:
        """Return the auth context for a session cookie, or ``None`` when it is not usable.

        ``None`` covers every failure the client should not be able to tell apart: unknown
        token, expired session, disabled account.
        """
        session = await self._sessions.get_by_token_hash(hash_token(token))
        if session is None:
            return None
        if session.expires_at <= utcnow():
            assert session.id is not None
            await self._sessions.delete(session.id)
            return None
        user = await self._users.get(session.user_id)
        if user is None or not user.is_active:
            return None
        assert session.id is not None
        await self._sessions.touch(session.id)
        return await self.context_for(user, session)

    async def context_for(self, user: User, session: Session) -> AuthContext:
        """Assemble the auth context from freshly read roles and memberships."""
        assert user.id is not None
        memberships = await self._memberships.list_for_user(user.id)
        return AuthContext(user=user, session=session, memberships=tuple(memberships))

    async def logout(self, token: str) -> bool:
        """Revoke one session; ``True`` when a session was actually removed."""
        return await self._sessions.revoke_by_token_hash(hash_token(token))
