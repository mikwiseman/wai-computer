"""Public share links for recordings.

A share is an unguessable ``secrets.token_urlsafe(32)`` URL; only the sha256
of the token is stored, so a link can never be re-derived after creation —
callers mint a link exactly when they need one and pass the URL along.
Shares are revocable (``revoked_at``) and the public page is noindex.

Shared by the owner-facing REST endpoint and the Telegram bot (which attaches
a "recording page" button to every imported recording).
"""

from __future__ import annotations

import secrets
import uuid
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.recording import RecordingShare


class ShareTokenCollisionError(RuntimeError):
    """Could not mint a unique share token (astronomically unlikely)."""


def share_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def shared_recording_url(token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/share/{token}"


async def generate_unique_share_token(db: AsyncSession) -> tuple[str, str]:
    for _ in range(5):
        token = secrets.token_urlsafe(32)
        token_hash = share_token_hash(token)
        existing_result = await db.execute(
            select(RecordingShare.id).where(RecordingShare.token_hash == token_hash)
        )
        if existing_result.scalar_one_or_none() is None:
            return token, token_hash
    raise ShareTokenCollisionError("Unable to mint a unique share token")


async def create_recording_share(
    db: AsyncSession,
    *,
    recording_id: uuid.UUID,
) -> tuple[RecordingShare, str, str]:
    """Mint a share row for a recording; returns ``(share, token, public_url)``.

    The caller owns the commit — this only stages the row, so it composes with
    whatever transaction the caller is already in.
    """
    token, token_hash = await generate_unique_share_token(db)
    share = RecordingShare(recording_id=recording_id, token_hash=token_hash)
    db.add(share)
    return share, token, shared_recording_url(token)
