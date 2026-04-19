"""Edge case tests for authentication endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_register_whitespace_only_password_rejected(client: AsyncClient):
    """Registration with whitespace-only password should be rejected."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "ws@example.com", "password": "        "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_password_padded_with_whitespace_rejected(client: AsyncClient):
    """Password with short content padded by spaces should be rejected."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "padded@example.com", "password": "pass    "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_password_exactly_8_chars(client: AsyncClient):
    """Registration with exactly 8-char password should succeed."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "exact8@example.com", "password": "abcdefgh"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_register_password_7_chars_rejected(client: AsyncClient):
    """Registration with 7-char password should be rejected."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "short7@example.com", "password": "abcdefg"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_with_different_case_email(client: AsyncClient):
    """Login with different case email should work (Pydantic normalizes)."""
    await client.post(
        "/api/auth/register",
        json={"email": "CaseTest@Example.COM", "password": "password123"},
    )

    response = await client.post(
        "/api/auth/login",
        json={"email": "casetest@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_uppercase_after_lowercase_register(client: AsyncClient):
    """Login with uppercase email after lowercase registration should work."""
    await client.post(
        "/api/auth/register",
        json={"email": "lower@example.com", "password": "password123"},
    )

    response = await client.post(
        "/api/auth/login",
        json={"email": "LOWER@EXAMPLE.COM", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_register_duplicate_different_case(client: AsyncClient):
    """Registering same email with different case should fail."""
    await client.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "password": "password123"},
    )

    response = await client.post(
        "/api/auth/register",
        json={"email": "DUP@EXAMPLE.COM", "password": "password456"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Unable to create account. Try signing in or request a magic link."
    )


@pytest.mark.asyncio
async def test_verify_magic_link_nonexistent_token(client: AsyncClient):
    """Verifying a token that doesn't exist should return 401."""
    response = await client.post(
        "/api/auth/verify-magic",
        json={"token": "this-token-does-not-exist"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_verify_magic_link_empty_token(client: AsyncClient):
    """Verifying an empty token string should return an error."""
    response = await client.post(
        "/api/auth/verify-magic",
        json={"token": ""},
    )
    # Either 401 or 422 is acceptable
    assert response.status_code in (401, 422)


@pytest.mark.asyncio
async def test_verify_magic_link_cannot_be_reused(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Magic link token should not be reusable after first verification."""
    captured: dict[str, str] = {}

    async def fake_send(to_email: str, token: str, **kwargs) -> None:
        captured["token"] = token

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send)

    await client.post("/api/auth/magic-link", json={"email": "reuse@example.com"})

    # First verification succeeds
    first = await client.post(
        "/api/auth/verify-magic",
        json={"token": captured["token"]},
    )
    assert first.status_code == 200

    # Second verification with same token should fail
    second = await client.post(
        "/api/auth/verify-magic",
        json={"token": captured["token"]},
    )
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_magic_link_expired_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Token that just expired (1 second ago) should be rejected."""
    user = User(
        email="boundary@example.com",
        magic_link_token="boundary-token",
        magic_link_expires=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post(
        "/api/auth/verify-magic",
        json={"token": "boundary-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_generic_error(client: AsyncClient):
    """Login with nonexistent email should return generic error (no info leak)."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "nonexistent@example.com", "password": "password123"},
    )
    assert response.status_code == 401
    detail = response.json()["detail"]
    # Should NOT reveal whether the email exists
    assert "Invalid email or password" in detail


@pytest.mark.asyncio
async def test_me_with_invalid_bearer_token(client: AsyncClient):
    """GET /me with invalid bearer token should return 401."""
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid-token-xyz"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_empty_bearer(client: AsyncClient):
    """GET /me with empty bearer should return 401."""
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_invalid_email_format(client: AsyncClient):
    """Registration with invalid email format should return 422."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_at_sign(client: AsyncClient):
    """Registration with email missing @ should return 422."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "userexample.com", "password": "password123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_missing_password_field(client: AsyncClient):
    """Login without password field should return 422."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "test@example.com"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_email_field(client: AsyncClient):
    """Register without email field should return 422."""
    response = await client.post(
        "/api/auth/register",
        json={"password": "password123"},
    )
    assert response.status_code == 422
