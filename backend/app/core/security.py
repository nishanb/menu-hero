"""Opaque-token helpers shared by sessions and invites.

Session and invite tokens are random strings, never signed payloads: the server looks the
token up, so revocation and role changes take effect on the very next request. Only the
SHA-256 digest is stored, matching the ``*_hash`` convention the HLD uses for table tokens
and API keys - a database dump therefore leaks no usable credential.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32
"""Entropy per token (256 bits, URL-safe base64 -> 43 characters)."""


def generate_token() -> str:
    """Return a fresh URL-safe token. The plaintext is shown to the client exactly once."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the stored form of ``token`` (hex SHA-256).

    Plain SHA-256 rather than a password KDF on purpose: these are 256-bit random tokens,
    so there is no low-entropy secret for an attacker to grind.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    """Constant-time comparison of ``token`` against a stored digest."""
    return secrets.compare_digest(hash_token(token), token_hash)
