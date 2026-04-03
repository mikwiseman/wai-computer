"""Tests for realtime voice session routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.voice_runtime import RealtimeVoiceSession
from app.main import app


@pytest.fixture
def mock_authenticated_user():
    """Patch get_current_user to return a fake user."""
    from app.api.deps import get_current_user

    fake_user = MagicMock()
    fake_user.id = "user-voice"

    async def _override():
        return fake_user

    app.dependency_overrides[get_current_user] = _override
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_realtime_voice_session_returns_signed_url(mock_authenticated_user):
    session = RealtimeVoiceSession(
        provider="elevenlabs",
        mode="conversation",
        agent_id="agent-123",
        signed_url="wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent-123",
        expires_in_seconds=900,
        environment="production",
        branch_id=None,
    )

    with patch(
        "app.api.routes.realtime_voice.create_realtime_voice_session",
        new=AsyncMock(return_value=session),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"mode": "conversation"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "elevenlabs"
    assert payload["agent_id"] == "agent-123"
    assert payload["signed_url"].startswith("wss://api.elevenlabs.io/")
    assert payload["expires_in_seconds"] == 900


@pytest.mark.asyncio
async def test_realtime_voice_session_returns_503_on_missing_config(mock_authenticated_user):
    with patch(
        "app.api.routes.realtime_voice.create_realtime_voice_session",
        new=AsyncMock(
            side_effect=ValueError(
                "No ElevenLabs agent configured for realtime voice mode: conversation"
            )
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"mode": "conversation"},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Voice mode is temporarily unavailable. Please try again in a moment."
    )


@pytest.mark.asyncio
async def test_realtime_voice_session_requires_auth():
    app.dependency_overrides.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/voice/session", json={"mode": "conversation"})

    assert response.status_code == 401
