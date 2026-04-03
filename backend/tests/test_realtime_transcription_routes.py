"""Tests for realtime transcription session routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.realtime_transcription import RealtimeTranscriptionSession
from app.main import app


@pytest.fixture
def mock_authenticated_user():
    """Patch get_current_user to return a fake user."""
    from app.api.deps import get_current_user

    fake_user = MagicMock()
    fake_user.id = "user-transcription"

    async def _override():
        return fake_user

    app.dependency_overrides[get_current_user] = _override
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_realtime_transcription_session_returns_provider_payload(mock_authenticated_user):
    session = RealtimeTranscriptionSession(
        provider="elevenlabs",
        token="sutkn_123",
        expires_in_seconds=900,
        sample_rate=16_000,
        audio_format="pcm_16000",
        language="multi",
        channels=1,
        model="scribe_v2_realtime",
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
    )

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(return_value=session),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "multi", "channels": 1},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "elevenlabs"
    assert payload["token"] == "sutkn_123"
    assert payload["model"] == "scribe_v2_realtime"
    assert payload["commit_strategy"] == "vad"


@pytest.mark.asyncio
async def test_realtime_transcription_session_returns_503_on_missing_config(
    mock_authenticated_user,
):
    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(side_effect=ValueError("ELEVENLABS_API_KEY not configured")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "en", "channels": 1},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Live transcription is temporarily unavailable. Please try again in a moment."
    )


@pytest.mark.asyncio
async def test_realtime_transcription_session_requires_auth():
    app.dependency_overrides.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/transcription/session",
            json={"language": "en", "channels": 1},
        )

    assert response.status_code == 401
