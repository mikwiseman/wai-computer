"""Tests for the Deepgram temporary token endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Request, Response

from app.main import app


@pytest.fixture
def mock_authenticated_user():
    """Patch get_current_user to return a fake user."""
    from app.api.deps import get_current_user

    fake_user = MagicMock()
    fake_user.id = "user-123"

    async def _override():
        return fake_user

    app.dependency_overrides[get_current_user] = _override
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_deepgram_token_returns_jwt(mock_authenticated_user):
    """Happy path: returns Deepgram JWT when API key is configured."""
    fake_response = Response(
        200,
        json={"access_token": "dg-temp-jwt", "expires_in": 300},
        request=Request("POST", "https://api.deepgram.com/v1/auth/grant"),
    )

    with (
        patch("app.api.routes.deepgram.settings") as mock_settings,
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fake_response),
    ):
        mock_settings.deepgram_api_key = "test-dg-key"

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/deepgram-token",
                headers={"Authorization": "Bearer fake-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "dg-temp-jwt"
    assert data["expires_in"] == 300


@pytest.mark.asyncio
async def test_deepgram_token_502_on_deepgram_error(mock_authenticated_user):
    """Returns 502 when Deepgram rejects the request."""
    fake_response = Response(
        403,
        json={"err_code": "FORBIDDEN", "err_msg": "Insufficient permissions."},
        request=Request("POST", "https://api.deepgram.com/v1/auth/grant"),
    )

    with (
        patch("app.api.routes.deepgram.settings") as mock_settings,
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fake_response),
    ):
        mock_settings.deepgram_api_key = "bad-key"

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/deepgram-token",
                headers={"Authorization": "Bearer fake-token"},
            )

    assert resp.status_code == 502
    assert "Deepgram token request failed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_deepgram_token_503_when_no_api_key(mock_authenticated_user):
    """Returns 503 when DEEPGRAM_API_KEY is not configured."""
    with patch("app.api.routes.deepgram.settings") as mock_settings:
        mock_settings.deepgram_api_key = ""

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/deepgram-token",
                headers={"Authorization": "Bearer fake-token"},
            )

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_deepgram_token_requires_auth():
    """Returns 401 when no auth token provided."""
    app.dependency_overrides.clear()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/deepgram-token")

    assert resp.status_code == 401
