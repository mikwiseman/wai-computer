"""Symmetric encryption for at-rest secrets (e.g. third-party MCP tokens).

We must store OAuth/PAT tokens for the user's connected MCP servers so the
sync worker can authenticate later. Storing them in plaintext would be a
credential-leak risk, so they are Fernet-encrypted at rest.

The Fernet key is derived from the existing ``jwt_secret`` via SHA-256 →
urlsafe-base64, so there is no NEW secret to provision on the server (one less
deploy dependency). Rotating ``jwt_secret`` invalidates stored tokens, which
is acceptable: the user simply reconnects the MCP server.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretDecryptError(Exception):
    """A stored secret could not be decrypted (key rotated or corrupt)."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = get_settings().jwt_secret.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string; returns a urlsafe token (str)."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a token from :func:`encrypt_secret`. Raises on tampering/rotation."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptError("could not decrypt stored secret") from exc
