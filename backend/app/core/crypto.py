"""Reversible encryption for the few secrets that cannot be stored as a digest.

Session and invite tokens are hashed (:mod:`app.core.security`) because the server only
ever needs to *recognise* them. A Google refresh token is different: it has to be replayed
verbatim at Google's token endpoint, so it must come back out again. It is therefore
encrypted rather than hashed, and a database dump on its own yields nothing usable without
``SECRET_KEY``.

``cryptography``'s Fernet does the work - authenticated AES-128-CBC with an HMAC, with the
nonce, the timestamp and the version handled for us. The key is derived from ``SECRET_KEY``
with HKDF under a fixed ``info`` label, so ``SECRET_KEY`` stays the single secret an
operator manages and can still be used for other purposes without key reuse.

Rotating ``SECRET_KEY`` invalidates every stored token: :meth:`TokenCipher.decrypt` returns
``None`` rather than raising, and the caller treats that exactly like "not connected", which
sends the person back through the consent screen.
"""

from __future__ import annotations

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

KEY_INFO = b"menuhero.oauth-token.v1"
"""HKDF ``info`` label: binds the derived key to this one purpose."""

FERNET_KEY_BYTES = 32


class MissingSecretKeyError(RuntimeError):
    """No ``SECRET_KEY`` is configured, so nothing can be encrypted at rest."""


def derive_fernet_key(secret_key: str) -> bytes:
    """Derive a Fernet key from the application secret."""
    if not secret_key:
        raise MissingSecretKeyError(
            "SECRET_KEY must be set before OAuth refresh tokens can be stored"
        )
    material = HKDF(
        algorithm=hashes.SHA256(), length=FERNET_KEY_BYTES, salt=None, info=KEY_INFO
    ).derive(secret_key.encode("utf-8"))
    return base64.urlsafe_b64encode(material)


class TokenCipher:
    """Encrypts and decrypts one kind of stored credential.

    Built per request from ``Settings``; deriving the key is a single HKDF pass, which is
    cheap enough that caching it would only add a lifecycle to reason about.
    """

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(derive_fernet_key(secret_key))

    def encrypt(self, plaintext: str) -> str:
        """Return the stored form of ``plaintext`` (URL-safe base64 Fernet token)."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str | None:
        """Return the plaintext, or ``None`` when it cannot be read back.

        ``None`` covers a rotated ``SECRET_KEY`` and a corrupted value alike. Both mean the
        stored credential is gone, which is a state the caller already has to handle.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            logger.warning("stored credential could not be decrypted; treating as disconnected")
            return None
