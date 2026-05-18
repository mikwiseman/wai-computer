"""Tests for small uncovered branches across multiple files — auth refresh
expired, realtime_voice generic exception, dictation route guards, etc.

Pushes backend coverage from 94.74% over the 95% threshold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# auth.py refresh — missing token + invalid + expired (lines 391-408)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_without_token_returns_401(client: AsyncClient) -> None:
    """Hit /api/auth/refresh with no body and no cookie — exercises the
    "missing token" branch on line 391-392."""
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert "Refresh token required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_with_invalid_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": "totally-bogus"},
    )
    assert resp.status_code == 401
    assert "Invalid refresh token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_with_expired_token_returns_401(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Insert an expired refresh token row and verify the cleanup branch."""
    from app.core.security import hash_refresh_token
    from app.models.refresh_token import RefreshToken as RefreshTokenModel
    from app.models.user import User

    user = User(
        email=f"refresh-exp-{uuid4().hex[:8]}@example.com",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.flush()

    raw_token = "expired-refresh-token-secret"
    db_session.add(RefreshTokenModel(
        token_hash=hash_refresh_token(raw_token),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # past
    ))
    await db_session.commit()

    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": raw_token},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# realtime_voice.py: generic Exception branch (lines 69-79)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_realtime_voice_unexpected_exception_returns_503(
    client: AsyncClient, auth_headers: dict,
) -> None:
    """When create_realtime_voice_session raises something other than ValueError,
    the generic Exception branch fires."""
    with patch(
        "app.api.routes.realtime_voice.create_realtime_voice_session",
        new=AsyncMock(side_effect=RuntimeError("internal boom")),
    ):
        resp = await client.post(
            "/api/voice/session",
            headers=auth_headers,
            json={"mode": "conversation"},
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_realtime_voice_value_error_returns_503(
    client: AsyncClient, auth_headers: dict,
) -> None:
    """ValueError branch (lines 58-67) — provider misconfigured."""
    with patch(
        "app.api.routes.realtime_voice.create_realtime_voice_session",
        new=AsyncMock(side_effect=ValueError("provider missing key")),
    ):
        resp = await client.post(
            "/api/voice/session",
            headers=auth_headers,
            json={"mode": "conversation"},
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# summarizer.py: small gaps (lines 269-271, 362)
# ---------------------------------------------------------------------------


def test_summarizer_module_imports() -> None:
    """Smoke import — covers top-level constant + module-load branches."""
    from app.core import summarizer

    assert hasattr(summarizer, "summarize_transcript")
    assert hasattr(summarizer, "generate_title")


# ---------------------------------------------------------------------------
# transcript_utils.py: line 23 (detect_wav_channels guard)
# ---------------------------------------------------------------------------


def test_detect_wav_channels_invalid_header_returns_one() -> None:
    """Audio data not starting with RIFF/WAVE defaults to mono (1)."""
    from app.core.transcript_utils import detect_wav_channels

    # 44 bytes but not a RIFF/WAVE prefix
    fake_header = b"NOTRIFF" + b"\x00" * 37
    assert detect_wav_channels(fake_header) == 1


def test_detect_wav_channels_too_short_returns_one() -> None:
    from app.core.transcript_utils import detect_wav_channels

    assert detect_wav_channels(b"short") == 1


def test_detect_wav_channels_valid_mono_returns_one() -> None:
    from app.core.transcript_utils import detect_wav_channels

    header = (
        b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE"
        + b"fmt " + b"\x10\x00\x00\x00"
        + b"\x01\x00"
        + b"\x01\x00"  # 1 channel
        + b"\x80\x3e\x00\x00"
        + b"\x00\x7d\x00\x00"
        + b"\x02\x00"
        + b"\x10\x00"
        + b"data" + b"\x00\x00\x00\x00"
    )
    assert detect_wav_channels(header) == 1


def test_detect_wav_channels_valid_stereo_returns_two() -> None:
    from app.core.transcript_utils import detect_wav_channels

    header = (
        b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE"
        + b"fmt " + b"\x10\x00\x00\x00"
        + b"\x01\x00"
        + b"\x02\x00"  # 2 channels at offset 22-23
        + b"\x80\x3e\x00\x00"
        + b"\x00\xfa\x00\x00"
        + b"\x04\x00"
        + b"\x10\x00"
        + b"data" + b"\x00\x00\x00\x00"
    )
    assert len(header) >= 44, f"need ≥44 bytes, got {len(header)}"
    assert detect_wav_channels(header) == 2


# ---------------------------------------------------------------------------
# transcription.py: line 50 (unsupported provider branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_unsupported_provider_raises() -> None:
    """Module-level dispatch should raise for an unknown provider."""
    from app.core.transcription import transcribe_audio_file

    with pytest.raises((ValueError, KeyError, RuntimeError)):
        await transcribe_audio_file(
            provider="not-a-real-provider",
            model="anything",
            audio_data=b"\x00" * 100,
            language="en",
        )
