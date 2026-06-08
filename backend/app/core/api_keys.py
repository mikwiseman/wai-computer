"""API key (Personal Access Token) generation and verification.

A WaiComputer API key is a static ``wc_live_<random>`` string passed as a Bearer
token. It is the machine-to-machine credential for headless/cron consumers, as an
alternative to the interactive OAuth flow. Only the SHA-256 hash is stored; the
plaintext is shown once at creation.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey

API_KEY_PREFIX = "wc_live_"
API_KEY_READ_SCOPE = "read"
# Opt-in scope that unlocks the MCP ``remember`` write tool for a token. The
# REST API stays read-only for every api key regardless (enforced in deps.py);
# this only widens the MCP surface, and only when the user explicitly grants it.
API_KEY_WRITE_SCOPE = "memory:write"


def is_api_key(token: str) -> bool:
    """True if the token looks like a WaiComputer API key."""
    return token.startswith(API_KEY_PREFIX)


def hash_api_key(token: str) -> str:
    """Hash an API key for storage and lookup (256-bit entropy → SHA-256 is fine)."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str, str]:
    """Generate a new key. Returns ``(plaintext, token_hash, prefix, last4)``.

    ``prefix`` (e.g. ``wc_live_ab12``) and ``last4`` are non-secret display aids.
    """
    plaintext = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, hash_api_key(plaintext), plaintext[: len(API_KEY_PREFIX) + 4], plaintext[-4:]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_api_key(db: AsyncSession, token: str) -> ApiKey | None:
    """Return the live ``ApiKey`` for a token (not revoked, not expired).

    Stamps ``last_used_at`` on success. Returns None for unknown/revoked/expired.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.token_hash == hash_api_key(token),
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None
    if api_key.expires_at is not None and api_key.expires_at <= _now():
        return None
    api_key.last_used_at = _now()
    return api_key
