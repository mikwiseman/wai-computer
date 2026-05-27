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
        provider="openai",
        token="ek_openai",
        expires_in_seconds=60,
        sample_rate=24_000,
        audio_format="pcm_24000",
        language="multi",
        channels=1,
        model="gpt-realtime-whisper",
        keep_alive_interval_seconds=None,
        commit_strategy="manual",
        no_verbatim=False,
        websocket_url="wss://api.openai.com/v1/realtime?intent=transcription",
        auth_scheme="bearer",
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
    assert payload["provider"] == "openai"
    assert payload["token"] == "ek_openai"
    assert payload["model"] == "gpt-realtime-whisper"
    assert payload["sample_rate"] == 24_000
    assert payload["audio_format"] == "pcm_24000"
    assert payload["commit_strategy"] == "manual"
    assert payload["no_verbatim"] is False
    assert payload["auth_scheme"] == "bearer"


@pytest.mark.asyncio
async def test_realtime_transcription_session_reports_slow_session_mint(
    mock_authenticated_user,
):
    session = RealtimeTranscriptionSession(
        provider="openai",
        token="ek_openai",
        expires_in_seconds=60,
        sample_rate=24_000,
        audio_format="pcm_24000",
        language="multi",
        channels=1,
        model="gpt-realtime-whisper",
        commit_strategy="manual",
        no_verbatim=False,
        websocket_url="wss://api.openai.com/v1/realtime?intent=transcription",
        auth_scheme="bearer",
    )
    captured: dict[str, object] = {}

    def fake_anomaly(
        code: str,
        message: str,
        *,
        category: str,
        extras: dict[str, object] | None = None,
    ) -> None:
        captured["code"] = code
        captured["message"] = message
        captured["category"] = category
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(return_value=session),
    ), patch(
        "app.api.routes.realtime_transcription.perf_counter",
        side_effect=[0.0, 3.0],
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_anomaly",
        new=fake_anomaly,
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
    assert captured["code"] == "realtime.session_mint.slow"
    assert captured["category"] == "transcription.session"
    assert captured["extras"] is not None
    assert captured["extras"]["provider"] == "openai"
    assert captured["extras"]["model"] == "gpt-realtime-whisper"
    assert captured["extras"]["latency_ms"] == 3_000


@pytest.mark.asyncio
async def test_realtime_transcription_session_returns_503_on_missing_config(
    mock_authenticated_user,
):
    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(side_effect=ValueError("OPENAI_API_KEY not configured")),
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
async def test_realtime_transcription_session_captures_sentry_on_unexpected_error(
    mock_authenticated_user,
):
    captured: dict[str, object] = {}

    def fake_capture(error: Exception, *, extras: dict[str, object] | None = None) -> None:
        captured["error"] = error
        captured["extras"] = extras

    with patch(
        "app.api.routes.realtime_transcription.create_realtime_transcription_session",
        new=AsyncMock(side_effect=RuntimeError("provider exploded")),
    ), patch(
        "app.api.routes.realtime_transcription.capture_sentry_exception",
        new=fake_capture,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/transcription/session",
                headers={"Authorization": "Bearer fake-token"},
                json={"language": "multi", "channels": 2},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Live transcription is temporarily unavailable. Please try again in a moment."
    )
    assert isinstance(captured["error"], RuntimeError)
    assert captured["extras"] is not None
    assert captured["extras"]["alert_code"] == "realtime.session_mint.failed"
    assert captured["extras"]["language"] == "multi"
    assert captured["extras"]["channels"] == 2
    assert captured["extras"]["purpose"] == "recording"
    assert isinstance(captured["extras"]["latency_ms"], int)


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
