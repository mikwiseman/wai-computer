"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    """Test user registration."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_accepts_region_and_me_returns_region(client: AsyncClient):
    """Mac RU builds must be able to seed billing region at signup."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "region@example.com",
            "password": "password123",
            "region": "ru",
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    me_response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["region"] == "ru"


@pytest.mark.asyncio
async def test_register_rejects_unknown_region(client: AsyncClient):
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "bad-region@example.com",
            "password": "password123",
            "region": "mars",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Duplicate password registration should not reveal account existence by status."""
    # First registration
    await client.post(
        "/api/auth/register",
        json={"email": "duplicate@example.com", "password": "password123"},
    )

    # Second registration with same email
    response = await client.post(
        "/api/auth/register",
        json={"email": "duplicate@example.com", "password": "password456"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "message": "Unable to create account. Try signing in or request a magic link."
    }


@pytest.mark.asyncio
async def test_register_duplicate_email_localizes_generic_error(client: AsyncClient):
    """Duplicate registration keeps the same 2xx status and returns localized copy."""
    await client.post(
        "/api/auth/register",
        json={"email": "duplicate.ru@example.com", "password": "password123"},
    )

    response = await client.post(
        "/api/auth/register",
        json={
            "email": "duplicate.ru@example.com",
            "password": "password456",
            "locale": "ru",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "message": "Не получилось создать аккаунт. Попробуй войти или запросить ссылку для входа."
    }


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    """Test user login."""
    # Register first
    await client.post(
        "/api/auth/register",
        json={"email": "login@example.com", "password": "password123"},
    )

    # Login
    response = await client.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    """Test login with invalid password."""
    # Register first
    await client.post(
        "/api/auth/register",
        json={"email": "invalid@example.com", "password": "password123"},
    )

    # Login with wrong password
    response = await client.post(
        "/api/auth/login",
        json={"email": "invalid@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    """Test registration with a password shorter than 8 characters is rejected."""
    response = await client.post(
        "/api/auth/register",
        json={"email": "short@example.com", "password": "abc"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test login with email that doesn't exist returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_credentials_localized_without_enumeration(client: AsyncClient):
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "nobody.ru@example.com",
            "password": "password123",
            "locale": "ru",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный email или пароль"


@pytest.mark.asyncio
async def test_me_endpoint_returns_user(client: AsyncClient):
    """Test GET /api/auth/me returns full user data with valid token."""
    reg_response = await client.post(
        "/api/auth/register",
        json={"email": "medata@example.com", "password": "password123"},
    )
    token = reg_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "medata@example.com"
    assert "id" in data
    assert "created_at" in data
    assert data["has_password"] is True


@pytest.mark.asyncio
async def test_me(client: AsyncClient, auth_headers: dict):
    """Test getting current user info."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "id" in data


@pytest.mark.asyncio
async def test_delete_me_removes_account(client: AsyncClient):
    """DELETE /api/auth/me permanently removes the user and blocks future access."""
    reg = await client.post(
        "/api/auth/register",
        json={"email": "delete-me@example.com", "password": "password123"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    delete_resp = await client.delete("/api/auth/me", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["message"] == "Account deleted"

    # Token still valid as a JWT, but the user row is gone → /me should 401
    me_resp = await client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 401

    # The email is free again — we can re-register with it
    re_reg = await client.post(
        "/api/auth/register",
        json={"email": "delete-me@example.com", "password": "password123"},
    )
    assert re_reg.status_code == 200


@pytest.mark.asyncio
async def test_delete_me_requires_auth(client: AsyncClient):
    """Unauthenticated DELETE /api/auth/me must be rejected."""
    response = await client.delete("/api/auth/me")
    assert response.status_code == 401
