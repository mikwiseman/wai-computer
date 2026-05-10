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

    async def fake_send_magic_link_email(_: str, token: str, **kwargs) -> None:
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


@pytest.mark.asyncio
async def test_get_settings_returns_user_settings(client: AsyncClient):
    """GET /api/settings returns the authenticated user's settings."""
    headers = await _register(client, "settings.get@example.com", "password-123")

    response = await client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "default_language" in data
    assert data["summary_language"] == "auto"
    assert data["summary_style"] == "medium"
    assert data["summary_instructions"] is None
    assert data["dictation_live_stt_provider"] == "elevenlabs"
    assert data["dictation_live_stt_model"] == "scribe_v2_realtime"
    assert data["recording_live_stt_provider"] == "elevenlabs"
    assert data["recording_live_stt_model"] == "scribe_v2_realtime"
    assert data["file_stt_provider"] == "elevenlabs"
    assert data["file_stt_model"] == "scribe_v2"
    assert data["dictation_post_filter_enabled"] is True
    assert data["dictation_post_filter_provider"] == "anthropic"
    assert data["dictation_post_filter_model"] == "claude-3-5-haiku-20241022"


@pytest.mark.asyncio
async def test_change_password_rejects_short_new_password(client: AsyncClient):
    """New password shorter than 8 characters should be rejected with 422."""
    headers = await _register(client, "settings.short@example.com", "password-123")

    response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "password-123", "new_password": "short"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_missing_fields(client: AsyncClient):
    """Missing required fields should be rejected with 422."""
    headers = await _register(client, "settings.missing@example.com", "password-123")

    response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_rejects_empty_language(client: AsyncClient):
    """PATCH /api/settings with empty default_language should return 422."""
    headers = await _register(client, "settings.empty.lang@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"default_language": "  "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(client: AsyncClient):
    """Providing the wrong old password should be rejected with 400."""
    headers = await _register(client, "settings.wrongold@example.com", "correct-password-123")

    response = await client.post(
        "/api/settings/change-password",
        headers=headers,
        json={"current_password": "totally-wrong-password", "new_password": "new-password-456"},
    )
    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()

    # Verify the old password still works
    login_response = await client.post(
        "/api/auth/login",
        json={"email": "settings.wrongold@example.com", "password": "correct-password-123"},
    )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_update_settings_with_null_language(client: AsyncClient):
    """PATCH /api/settings with null default_language should not change it."""
    headers = await _register(client, "settings.null.lang@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"default_language": None},
    )
    assert response.status_code == 200
    # null is a no-op; the default_language should remain unchanged
    assert response.json()["default_language"] is not None


@pytest.mark.asyncio
async def test_update_settings_normalizes_language(client: AsyncClient):
    """PATCH /api/settings should normalize language to lowercase."""
    headers = await _register(client, "settings.norm.lang@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"default_language": "  EN  "},
    )
    assert response.status_code == 200
    assert response.json()["default_language"] == "en"


@pytest.mark.asyncio
async def test_change_password_requires_auth(client: AsyncClient):
    """Unauthenticated change-password should return 401."""
    response = await client.post(
        "/api/settings/change-password",
        json={"current_password": "x", "new_password": "new-password-123"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_settings_requires_auth(client: AsyncClient):
    """Unauthenticated GET /api/settings should return 401."""
    response = await client.get("/api/settings")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_summary_language(client: AsyncClient):
    """PATCH /api/settings should update summary_language."""
    headers = await _register(client, "settings.sumlang@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_language": "ru"},
    )
    assert response.status_code == 200
    assert response.json()["summary_language"] == "ru"

    # Verify persistence
    get_response = await client.get("/api/settings", headers=headers)
    assert get_response.json()["summary_language"] == "ru"


@pytest.mark.asyncio
async def test_update_summary_style(client: AsyncClient):
    """PATCH /api/settings should update summary_style."""
    headers = await _register(client, "settings.sumstyle@example.com", "password-123")

    for style in ("brief", "medium", "detailed"):
        response = await client.patch(
            "/api/settings",
            headers=headers,
            json={"summary_style": style},
        )
        assert response.status_code == 200
        assert response.json()["summary_style"] == style


@pytest.mark.asyncio
async def test_update_summary_style_rejects_invalid(client: AsyncClient):
    """PATCH /api/settings should reject invalid summary_style."""
    headers = await _register(client, "settings.badstyle@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_style": "ultra"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_summary_instructions(client: AsyncClient):
    """PATCH /api/settings should update summary_instructions."""
    headers = await _register(client, "settings.suminst@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_instructions": "Focus on action items and deadlines"},
    )
    assert response.status_code == 200
    assert response.json()["summary_instructions"] == "Focus on action items and deadlines"


@pytest.mark.asyncio
async def test_clear_summary_instructions(client: AsyncClient):
    """PATCH /api/settings with empty string should clear summary_instructions."""
    headers = await _register(client, "settings.clearinst@example.com", "password-123")

    # Set instructions
    await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_instructions": "Some instructions"},
    )

    # Clear instructions
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_instructions": ""},
    )
    assert response.status_code == 200
    assert response.json()["summary_instructions"] is None


@pytest.mark.asyncio
async def test_update_summary_language_normalizes(client: AsyncClient):
    """PATCH /api/settings should normalize summary_language to lowercase."""
    headers = await _register(client, "settings.normsummary@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"summary_language": "  RU  "},
    )
    assert response.status_code == 200
    assert response.json()["summary_language"] == "ru"


@pytest.mark.asyncio
async def test_get_transcription_options_returns_curated_choices(client: AsyncClient):
    """GET /api/settings/transcription-options returns shared model choices."""
    headers = await _register(client, "settings.options@example.com", "password-123")

    response = await client.get("/api/settings/transcription-options", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["dictation_live_stt"][0]["provider"] == "elevenlabs"
    assert data["dictation_live_stt"][0]["model"] == "scribe_v2_realtime"
    assert any(
        option["provider"] == "inworld" and option["model"] == "soniox/stt-rt-v4"
        for option in data["dictation_live_stt"]
    )
    assert any(
        option["provider"] == "inworld"
        and option["model"] == "assemblyai/universal-streaming-english"
        for option in data["dictation_live_stt"]
    )
    assert any(
        option["provider"] == "inworld" and option["model"] == "soniox/stt-rt-v4"
        for option in data["recording_live_stt"]
    )
    assert any(
        option["provider"] == "inworld" and option["model"] == "inworld/inworld-stt-1"
        for option in data["file_stt"]
    )
    assert any(option["model"] == "gpt-4o-transcribe" for option in data["file_stt"])
    assert any(option["model"] == "gpt-4o-transcribe-diarize" for option in data["file_stt"])
    assert any(
        option["model"] == "claude-3-5-haiku-20241022"
        for option in data["dictation_post_filter"]
    )


@pytest.mark.asyncio
async def test_update_transcription_settings_persists_valid_choices(client: AsyncClient):
    """PATCH /api/settings should persist curated transcription choices."""
    headers = await _register(client, "settings.stt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "dictation_live_stt_provider": "elevenlabs",
            "dictation_live_stt_model": "scribe_v2_realtime",
            "recording_live_stt_provider": "inworld",
            "recording_live_stt_model": "soniox/stt-rt-v4",
            "file_stt_provider": "inworld",
            "file_stt_model": "inworld/inworld-stt-1",
            "dictation_post_filter_enabled": False,
            "dictation_post_filter_provider": "anthropic",
            "dictation_post_filter_model": "claude-sonnet-4-20250514",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dictation_live_stt_provider"] == "elevenlabs"
    assert data["recording_live_stt_provider"] == "inworld"
    assert data["recording_live_stt_model"] == "soniox/stt-rt-v4"
    assert data["file_stt_provider"] == "inworld"
    assert data["file_stt_model"] == "inworld/inworld-stt-1"
    assert data["dictation_post_filter_enabled"] is False
    assert data["dictation_post_filter_model"] == "claude-sonnet-4-20250514"

    get_response = await client.get("/api/settings", headers=headers)
    assert get_response.json()["file_stt_model"] == "inworld/inworld-stt-1"


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_mismatched_pair(client: AsyncClient):
    """Provider/model pairs must be updated together."""
    headers = await _register(client, "settings.partialstt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"file_stt_provider": "openai"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_invalid_model(client: AsyncClient):
    """PATCH /api/settings should reject unknown provider/model choices."""
    headers = await _register(client, "settings.badstt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "dictation_live_stt_provider": "openai",
            "dictation_live_stt_model": "gpt-realtime-2",
        },
    )

    assert response.status_code == 422
