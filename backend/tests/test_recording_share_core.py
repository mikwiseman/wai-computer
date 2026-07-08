"""Tests for the recording share-link core (minting, hashing, URLs)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_share import (
    ShareTokenCollisionError,
    create_recording_share,
    generate_unique_share_token,
    share_token_hash,
    shared_recording_url,
)
from app.models.recording import Recording, RecordingShare, RecordingStatus
from app.models.user import User


def test_share_token_hash_is_sha256_hex() -> None:
    digest = share_token_hash("token-value")
    assert len(digest) == 64
    assert digest != share_token_hash("other-token")


def test_shared_recording_url_uses_frontend_url() -> None:
    url = shared_recording_url("abc123")
    assert url.endswith("/share/abc123")
    assert url.startswith("http")


@pytest.mark.asyncio
async def test_create_recording_share_persists_hash_only(db_session: AsyncSession) -> None:
    user = User(email="share-core@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="Shared",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    await db_session.flush()

    share, token, url = await create_recording_share(db_session, recording_id=recording.id)
    await db_session.commit()

    assert url.endswith(f"/share/{token}")
    stored = (
        await db_session.execute(
            select(RecordingShare).where(RecordingShare.recording_id == recording.id)
        )
    ).scalar_one()
    assert stored.token_hash == share_token_hash(token)
    assert token not in stored.token_hash
    assert stored.revoked_at is None
    assert share.recording_id == recording.id


@pytest.mark.asyncio
async def test_generate_unique_share_token_raises_after_persistent_collisions() -> None:
    fake_db = AsyncMock()
    fake_db.execute.return_value.scalar_one_or_none = lambda: uuid4()

    with patch("app.core.recording_share.secrets.token_urlsafe", return_value="collide"):
        with pytest.raises(ShareTokenCollisionError):
            await generate_unique_share_token(fake_db)
    assert fake_db.execute.await_count == 5
