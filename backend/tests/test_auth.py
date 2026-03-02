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
async def test_register_duplicate_email(client: AsyncClient):
    """Test registration with duplicate email."""
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
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


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
async def test_me(client: AsyncClient, auth_headers: dict):
    """Test getting current user info."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "id" in data
