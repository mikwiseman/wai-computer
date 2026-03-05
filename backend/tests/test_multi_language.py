"""Tests for multi-language transcription support."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

import app.core.deepgram as deepgram_module
from app.core.deepgram import DeepgramStreamingClient

# ---------------------------------------------------------------------------
# Deepgram: endpointing=100 for multi-language
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_deepgram_settings():
    """Patch settings on the already-imported module for each test."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", "dg-test-key-123"):
        yield


class TestDeepgramMultiLanguage:
    def test_multi_language_adds_endpointing(self):
        """When language is 'multi', _build_url includes endpointing=100."""
        client = DeepgramStreamingClient(language="multi")
        url = client._build_url()
        assert "language=multi" in url
        assert "endpointing=100" in url

    def test_single_language_no_endpointing(self):
        """When language is a specific code, endpointing is NOT added."""
        client = DeepgramStreamingClient(language="en")
        url = client._build_url()
        assert "language=en" in url
        assert "endpointing" not in url

    def test_other_language_no_endpointing(self):
        """Endpointing is only added for 'multi', not for other language codes."""
        client = DeepgramStreamingClient(language="es")
        url = client._build_url()
        assert "language=es" in url
        assert "endpointing" not in url


# ---------------------------------------------------------------------------
# Recording creation: language from request vs user default
# ---------------------------------------------------------------------------


async def _register(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_recording_with_explicit_language(client: AsyncClient, auth_headers: dict):
    """Recording should use the explicitly provided language."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Spanish Meeting", "type": "meeting", "language": "es"},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "es"


@pytest.mark.asyncio
async def test_create_recording_with_multi_language(client: AsyncClient, auth_headers: dict):
    """Recording should accept 'multi' as a language value."""
    response = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": "Multi Language", "type": "note", "language": "multi"},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "multi"


@pytest.mark.asyncio
async def test_create_recording_defaults_to_user_language(client: AsyncClient):
    """When no language specified, recording uses user's default_language."""
    headers = await _register(client, "multilang@example.com", "password123")

    # Default user language is "multi" (from server_default)
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": "Default Language", "type": "note"},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "multi"


@pytest.mark.asyncio
async def test_create_recording_uses_updated_user_language(client: AsyncClient):
    """After changing default_language, new recordings should use the updated value."""
    headers = await _register(client, "updatedlang@example.com", "password123")

    # Update user's default language to French
    patch_response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"default_language": "fr"},
    )
    assert patch_response.status_code == 200

    # Create recording without specifying language
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": "French Note", "type": "note"},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "fr"


@pytest.mark.asyncio
async def test_create_recording_explicit_overrides_user_default(client: AsyncClient):
    """Explicit language in request overrides user default_language."""
    headers = await _register(client, "override@example.com", "password123")

    # Update user's default to German
    await client.patch("/api/settings", headers=headers, json={"default_language": "de"})

    # Create recording with explicit Spanish
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": "Override Test", "type": "note", "language": "es"},
    )
    assert response.status_code == 201
    assert response.json()["language"] == "es"


# ---------------------------------------------------------------------------
# Settings API: default_language
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_returns_default_language(client: AsyncClient):
    """GET /api/settings should return default_language."""
    headers = await _register(client, "settings.get@example.com", "password123")

    response = await client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["default_language"] == "multi"


@pytest.mark.asyncio
async def test_patch_settings_updates_default_language(client: AsyncClient):
    """PATCH /api/settings should update default_language."""
    headers = await _register(client, "settings.patch@example.com", "password123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"default_language": "ja"},
    )
    assert response.status_code == 200
    assert response.json()["default_language"] == "ja"

    # Verify it persists
    get_response = await client.get("/api/settings", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["default_language"] == "ja"


@pytest.mark.asyncio
async def test_patch_settings_empty_body_keeps_existing(client: AsyncClient):
    """PATCH /api/settings with empty body should not change default_language."""
    headers = await _register(client, "settings.noop@example.com", "password123")

    # Set language to Korean first
    await client.patch("/api/settings", headers=headers, json={"default_language": "ko"})

    # Patch with empty body
    response = await client.patch("/api/settings", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["default_language"] == "ko"
