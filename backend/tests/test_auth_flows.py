"""Additional authentication endpoint tests."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User

settings = get_settings()


@pytest.mark.asyncio
async def test_refresh_requires_auth(client: AsyncClient):
    """Refresh endpoint should require a bearer token."""
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_auth_returns_token(client: AsyncClient, auth_headers: dict):
    """Refresh endpoint should return a token for authenticated users."""
    response = await client.post("/api/auth/refresh", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert settings.auth_cookie_name in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_register_sets_auth_cookie(client: AsyncClient):
    """Register should also set the HTTP-only auth cookie for browser clients."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "cookie.register@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.auth_cookie_name in set_cookie
    assert "HttpOnly" in set_cookie


@pytest.mark.asyncio
async def test_me_accepts_cookie_auth(client: AsyncClient):
    """Current-user endpoint should authenticate from auth cookie when bearer is absent."""
    register_response = await client.post(
        "/api/auth/register",
        json={"email": "cookie.me@example.com", "password": "password123"},
    )
    assert register_response.status_code == 200
    cookie = register_response.cookies.get(settings.auth_cookie_name)
    assert cookie

    client.cookies.set(settings.auth_cookie_name, cookie)
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "cookie.me@example.com"


@pytest.mark.asyncio
async def test_logout_clears_auth_cookie(client: AsyncClient):
    """Logout should clear auth cookie."""
    response = await client.post("/api/auth/logout")
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.auth_cookie_name in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()


@pytest.mark.asyncio
async def test_magic_link_creates_user_and_stores_token(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Magic-link request creates user when missing and stores token/expiry."""
    captured: dict[str, str] = {}

    def fake_send_magic_link_email(to_email: str, token: str) -> None:
        captured["to_email"] = to_email
        captured["token"] = token

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    email = "magic.new@example.com"
    response = await client.post("/api/auth/magic-link", json={"email": email})
    assert response.status_code == 200
    assert response.json()["message"] == "Magic link sent to your email"
    assert captured["to_email"] == email
    assert captured["token"]

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    assert user.magic_link_token == captured["token"]
    assert user.magic_link_expires is not None


@pytest.mark.asyncio
async def test_verify_magic_link_success_clears_token(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Successful verify should return JWT and clear magic-link token fields."""
    captured: dict[str, str] = {}

    def fake_send_magic_link_email(to_email: str, token: str) -> None:
        captured["token"] = token

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    email = "magic.verify@example.com"
    request_response = await client.post("/api/auth/magic-link", json={"email": email})
    assert request_response.status_code == 200

    verify_response = await client.post(
        "/api/auth/verify-magic",
        json={"token": captured["token"]},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["access_token"]

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    assert user.magic_link_token is None
    assert user.magic_link_expires is None


@pytest.mark.asyncio
async def test_verify_magic_link_expired_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Expired token should be rejected."""
    user = User(
        email="expired.magic@example.com",
        magic_link_token="expired-token",
        magic_link_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post("/api/auth/verify-magic", json={"token": "expired-token"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    """Current-user endpoint should require auth."""
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
