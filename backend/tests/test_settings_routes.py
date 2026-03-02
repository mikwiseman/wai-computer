"""Tests for settings endpoints."""

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_change_password_success_and_login_with_new_password(client: AsyncClient):
    """Password users should be able to rotate passwords."""
    email = "settings.success@example.com"
    old_password = "old-password-123"
    new_password = "new-password-456"
    headers = await _register(client, email, old_password)

    change_response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": old_password, "new_password": new_password},
    )
    assert change_response.status_code == 200

    old_login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": old_password},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": new_password},
    )
    assert new_login.status_code == 200
    assert new_login.json()["access_token"]


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(client: AsyncClient):
    """Wrong current password should be rejected."""
    headers = await _register(client, "settings.wrong@example.com", "password-123")

    response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "wrong-current", "new_password": "next-password"},
    )
    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_magic_link_user_can_set_password(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Magic-link users without password hash should be able to set a password."""
    captured: dict[str, str] = {}

    async def fake_send_magic_link_email(_: str, token: str) -> None:
        captured["token"] = token

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    email = "settings.magic@example.com"
    magic_response = await client.post("/api/auth/magic-link", json={"email": email})
    assert magic_response.status_code == 200

    verify_response = await client.post("/api/auth/verify-magic", json={"token": captured["token"]})
    assert verify_response.status_code == 200
    headers = {"Authorization": f"Bearer {verify_response.json()['access_token']}"}

    set_password_response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "", "new_password": "magic-password-123"},
    )
    assert set_password_response.status_code == 200
    assert "set successfully" in set_password_response.json()["message"].lower()

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "magic-password-123"},
    )
    assert login_response.status_code == 200
