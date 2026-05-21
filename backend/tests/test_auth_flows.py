"""Additional authentication endpoint tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.user import User

settings = get_settings()


def test_auth_cookie_secure_defaults_follow_frontend_url_scheme():
    """Local HTTP frontend should not require secure cookies; HTTPS should."""
    http_settings = Settings(jwt_secret="test-secret", frontend_url="http://localhost:3000")
    https_settings = Settings(
        jwt_secret="test-secret",
        frontend_url="https://wai.computer",
        auth_cookie_domain="wai.computer",
    )
    app_subdomain_settings = Settings(
        jwt_secret="test-secret",
        frontend_url="https://panel.wai.computer",
        auth_cookie_domain="wai.computer",
    )
    override_settings = Settings(
        jwt_secret="test-secret",
        frontend_url="http://localhost:3000",
        auth_cookie_secure=True,
    )

    assert http_settings.auth_cookie_secure_resolved is False
    assert https_settings.auth_cookie_secure_resolved is True
    assert http_settings.auth_cookie_domain_resolved is None
    assert https_settings.auth_cookie_domain_resolved == "wai.computer"
    assert app_subdomain_settings.auth_cookie_domain_resolved == "wai.computer"
    assert override_settings.auth_cookie_secure_resolved is True


@pytest.mark.asyncio
async def test_refresh_requires_valid_token(client: AsyncClient):
    """Refresh endpoint should reject an invalid refresh token."""
    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": "invalid-token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_valid_token_returns_tokens(client: AsyncClient):
    """Refresh endpoint should return new tokens for a valid refresh token."""
    # Register to get a refresh token
    email = f"refresh-test-{uuid4().hex}@example.com"
    reg_resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
    )
    reg_data = reg_resp.json()
    refresh_token = reg_data["refresh_token"]

    # Use refresh token
    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert settings.auth_cookie_name in response.headers.get("set-cookie", "")
    assert settings.auth_refresh_cookie_name in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_refresh_accepts_refresh_cookie_when_body_missing(client: AsyncClient):
    """Browser refresh should work from the refresh cookie without a JSON body."""
    email = f"refresh-cookie-{uuid4().hex}@example.com"
    reg_resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
    )
    assert reg_resp.status_code == 200

    refresh_cookie = reg_resp.cookies.get(settings.auth_refresh_cookie_name)
    assert refresh_cookie

    client.cookies.set(settings.auth_refresh_cookie_name, refresh_cookie)
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]


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
    assert settings.auth_refresh_cookie_name in set_cookie
    assert "HttpOnly" in set_cookie
    assert ("Secure" in set_cookie) is settings.auth_cookie_secure_resolved
    if settings.auth_cookie_domain_resolved:
        assert f"Domain={settings.auth_cookie_domain_resolved}" in set_cookie


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
    assert settings.auth_refresh_cookie_name in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()


@pytest.mark.asyncio
async def test_logout_revokes_refresh_cookie_without_request_body(client: AsyncClient):
    """Browser logout should revoke the cookie-backed refresh token."""
    email = f"logout-cookie-{uuid4().hex}@example.com"
    reg_resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
    )
    refresh_token = reg_resp.cookies.get(settings.auth_refresh_cookie_name)
    assert refresh_token

    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200

    client.cookies.set(settings.auth_refresh_cookie_name, refresh_token)
    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    client.cookies.set(settings.auth_refresh_cookie_name, refresh_token)
    refresh_after_logout = await client.post("/api/auth/refresh")
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_magic_link_creates_user_and_stores_token(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Magic-link request creates user when missing and stores token/expiry."""
    captured: dict[str, str] = {}

    async def fake_send_magic_link_email(to_email: str, token: str, **kwargs) -> None:
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
async def test_magic_link_creates_user_with_region(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Magic-link signup should preserve the client billing region."""

    async def fake_send_magic_link_email(to_email: str, token: str, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    email = "magic.region@example.com"
    response = await client.post(
        "/api/auth/magic-link",
        json={"email": email, "region": "ru"},
    )
    assert response.status_code == 200

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    assert user.region == "ru"


@pytest.mark.asyncio
async def test_register_sets_password_for_existing_magic_link_user(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """A passwordless magic-link account can later set a password via registration."""

    async def fake_send_magic_link_email(to_email: str, token: str, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    email = "magic.then.password@example.com"
    magic_response = await client.post(
        "/api/auth/magic-link",
        json={"email": email, "region": "ru"},
    )
    assert magic_response.status_code == 200

    register_response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "new-password-123", "region": "global"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["access_token"]

    me_response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["has_password"] is True
    assert me_response.json()["region"] == "ru"

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    assert user.password_hash is not None
    assert user.magic_link_token is None
    assert user.magic_link_expires is None


@pytest.mark.asyncio
async def test_verify_magic_link_success_clears_token(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Successful verify should return JWT and clear magic-link token fields."""
    captured: dict[str, str] = {}

    async def fake_send_magic_link_email(to_email: str, token: str, **kwargs) -> None:
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
    access_token = verify_response.json()["access_token"]
    assert access_token

    me_response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["has_password"] is False

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    assert user.magic_link_token is None
    assert user.magic_link_expires is None


@pytest.mark.asyncio
async def test_forgot_password_sends_reset_link_without_creating_unknown_user(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Forgot-password is explicit, localized, and non-enumerating."""
    captured: dict[str, str] = {}

    async def fake_send_password_reset_email(
        to_email: str,
        token: str,
        **kwargs,
    ) -> None:
        captured["to_email"] = to_email
        captured["token"] = token
        captured["locale"] = kwargs["locale"]

    monkeypatch.setattr(
        "app.core.email.send_password_reset_email",
        fake_send_password_reset_email,
        raising=False,
    )

    await client.post(
        "/api/auth/register",
        json={"email": "reset.existing@example.com", "password": "password123"},
    )

    existing_response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "reset.existing@example.com", "locale": "ru"},
    )
    assert existing_response.status_code == 200
    assert existing_response.json()["message"] == (
        "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля."
    )
    assert captured["to_email"] == "reset.existing@example.com"
    assert captured["token"].startswith("reset_")
    assert captured["locale"] == "ru"

    missing_response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "reset.missing@example.com", "locale": "ru"},
    )
    assert missing_response.status_code == 200
    assert missing_response.json() == existing_response.json()

    missing_result = await db_session.execute(
        select(User).where(User.email == "reset.missing@example.com")
    )
    assert missing_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_forgot_password_email_failure_keeps_non_enumerating_response(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Email delivery errors must not reveal whether a reset email exists."""

    async def fake_send_password_reset_email(*args, **kwargs) -> None:
        raise RuntimeError("email provider unavailable")

    monkeypatch.setattr(
        "app.core.email.send_password_reset_email",
        fake_send_password_reset_email,
        raising=False,
    )

    await client.post(
        "/api/auth/register",
        json={"email": "reset.fail@example.com", "password": "password123"},
    )

    existing_response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "reset.fail@example.com", "locale": "ru"},
    )
    missing_response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "reset.fail.missing@example.com", "locale": "ru"},
    )

    assert existing_response.status_code == 200
    assert missing_response.status_code == 200
    assert existing_response.json() == missing_response.json()


@pytest.mark.asyncio
async def test_reset_password_accepts_only_reset_tokens(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Password reset tokens must not be interchangeable with login magic links."""
    magic_user = User(
        email="reset.magic-token@example.com",
        magic_link_token="magic_token",
        magic_link_expires=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    reset_user = User(
        email="reset.valid-token@example.com",
        magic_link_token="reset_token",
        magic_link_expires=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db_session.add_all([magic_user, reset_user])
    await db_session.flush()

    magic_response = await client.post(
        "/api/auth/reset-password",
        json={"token": "magic_token", "password": "password1234"},
    )
    assert magic_response.status_code == 401
    assert magic_response.json()["detail"] == "Invalid password reset link"

    reset_response = await client.post(
        "/api/auth/reset-password",
        json={"token": "reset_token", "password": "password1234"},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["message"] == "Password reset successfully"

    await db_session.refresh(reset_user)
    assert reset_user.password_hash is not None
    assert reset_user.magic_link_token is None
    assert reset_user.magic_link_expires is None


@pytest.mark.asyncio
async def test_reset_password_errors_are_localized(client: AsyncClient):
    invalid_response = await client.post(
        "/api/auth/reset-password",
        json={"token": "magic_token", "password": "password1234", "locale": "ru"},
    )
    assert invalid_response.status_code == 401
    assert invalid_response.json()["detail"] == "Недействительная ссылка для сброса пароля"


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
