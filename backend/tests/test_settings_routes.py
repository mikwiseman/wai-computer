"""Tests for settings endpoints."""

import pytest
from httpx import AsyncClient

from tests.conftest import LEGAL_ACCEPTANCE


async def _register(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, **LEGAL_ACCEPTANCE},
    )
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
    magic_response = await client.post(
        "/api/auth/magic-link",
        json={"email": email, **LEGAL_ACCEPTANCE},
    )
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
    assert data["dictation_live_stt_provider"] == "deepgram"
    assert data["dictation_live_stt_model"] == "nova-3"
    assert data["recording_live_stt_provider"] == "deepgram"
    assert data["recording_live_stt_model"] == "nova-3"
    assert data["file_stt_provider"] == "deepgram"
    assert data["file_stt_model"] == "nova-3"
    assert data["dictation_post_filter_enabled"] is False
    assert data["dictation_cleanup_level"] == "none"
    assert data["dictation_post_filter_provider"] == "openai"
    assert data["dictation_post_filter_model"] == "gpt-5.5"


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
async def test_update_dictation_cleanup_level_persists_and_syncs_legacy_enabled(
    client: AsyncClient,
):
    """PATCH /api/settings should persist cleanup levels and keep old clients in sync."""
    headers = await _register(client, "settings.cleanup.level@example.com", "password-123")

    for level in ("none", "light", "medium", "high"):
        response = await client.patch(
            "/api/settings",
            headers=headers,
            json={"dictation_cleanup_level": level},
        )
        assert response.status_code == 200
        assert response.json()["dictation_cleanup_level"] == level
        assert response.json()["dictation_post_filter_enabled"] is (level != "none")

    get_response = await client.get("/api/settings", headers=headers)
    assert get_response.json()["dictation_cleanup_level"] == "high"
    assert get_response.json()["dictation_post_filter_enabled"] is True


@pytest.mark.asyncio
async def test_update_dictation_cleanup_level_rejects_invalid(client: AsyncClient):
    """PATCH /api/settings should reject unknown cleanup levels."""
    headers = await _register(client, "settings.cleanup.bad@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_cleanup_level": "extreme"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_legacy_dictation_post_filter_enabled_maps_to_cleanup_level(
    client: AsyncClient,
):
    """Old clients that only send the boolean should map true->light and false->none."""
    headers = await _register(client, "settings.cleanup.legacy@example.com", "password-123")

    enabled = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_post_filter_enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["dictation_cleanup_level"] == "light"
    assert enabled.json()["dictation_post_filter_enabled"] is True

    disabled = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_post_filter_enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["dictation_cleanup_level"] == "none"
    assert disabled.json()["dictation_post_filter_enabled"] is False


@pytest.mark.asyncio
async def test_cleanup_level_wins_when_consistent_legacy_boolean_is_present(
    client: AsyncClient,
):
    """A consistent legacy boolean must not collapse medium/high back to light."""
    headers = await _register(client, "settings.cleanup.consistent@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_cleanup_level": "medium", "dictation_post_filter_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["dictation_cleanup_level"] == "medium"


@pytest.mark.asyncio
async def test_cleanup_level_rejects_conflicting_legacy_boolean(client: AsyncClient):
    """If both fields are present, they must describe the same on/off state."""
    headers = await _register(client, "settings.cleanup.conflict@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_cleanup_level": "none", "dictation_post_filter_enabled": True},
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
async def test_get_transcription_options_returns_curated_choices(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """GET /api/settings/transcription-options returns configured curated choices."""
    headers = await _register(client, "settings.options@example.com", "password-123")
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "xi-key",
            "deepgram_api_key": "dg-key",
            "openai_api_key": "sk-key",
        },
    )()
    monkeypatch.setattr("app.api.routes.settings.get_app_settings", lambda: settings)

    response = await client.get("/api/settings/transcription-options", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["dictation_live_stt"] == [
        {
            "provider": "deepgram",
            "model": "nova-3",
            "label": "Deepgram Nova-3",
            "description": "Fixed low-latency streaming speech-to-text model for live dictation.",
        }
    ]
    assert data["recording_live_stt"] == [
        {
            "provider": "deepgram",
            "model": "nova-3",
            "label": "Deepgram Nova-3",
            "description": "Fixed low-latency streaming speech-to-text model for live recording.",
        }
    ]
    assert data["file_stt"] == [
        {
            "provider": "deepgram",
            "model": "nova-3",
            "label": "Deepgram Nova-3",
            "description": "Full-session batch transcription with v2 speaker diarization.",
        }
    ]
    assert data["dictation_post_filter"][0]["model"] == "gpt-5.5"
    assert all(
        option["model"] != "removed-file-model"
        for group in data.values()
        for option in group
    )


@pytest.mark.asyncio
async def test_get_transcription_options_hides_unconfigured_providers(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """The picker must not offer provider/model pairs that cannot mint real requests."""
    headers = await _register(client, "settings.configured.options@example.com", "password-123")
    settings = type(
        "Settings",
        (),
        {
            "elevenlabs_api_key": "xi-key",
            "openai_api_key": "",
        },
    )()
    monkeypatch.setattr("app.api.routes.settings.get_app_settings", lambda: settings)

    response = await client.get("/api/settings/transcription-options", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["dictation_live_stt"] == []
    assert data["recording_live_stt"] == []
    assert data["file_stt"] == []
    assert data["dictation_post_filter"] == []


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_model_changes(client: AsyncClient):
    """Provider/model choices are now managed centrally, not by user settings."""
    headers = await _register(client, "settings.stt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "file_stt_provider": "deepgram",
            "file_stt_model": "nova-3",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Transcription models are managed by WaiComputer."

    get_response = await client.get("/api/settings", headers=headers)
    assert get_response.json()["file_stt_model"] == "nova-3"


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_post_filter_model_change(
    client: AsyncClient,
):
    """The cleanup model is also fixed; only the enabled toggle remains user-controlled."""
    headers = await _register(client, "settings.unconfiguredstt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "dictation_post_filter_provider": "openai",
            "dictation_post_filter_model": "gpt-5.5",
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_mismatched_pair(client: AsyncClient):
    """Provider/model pairs must be updated together."""
    headers = await _register(client, "settings.partialstt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"file_stt_provider": "deepgram"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_transcription_settings_rejects_invalid_model(client: AsyncClient):
    """PATCH /api/settings rejects all provider/model fields before persistence."""
    headers = await _register(client, "settings.badstt@example.com", "password-123")

    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "dictation_live_stt_provider": "removed-provider",
            "dictation_live_stt_model": "removed-model",
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Appearance preferences (theme + accent) — see ThemeAccentPicker on the web.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preferences_returns_defaults_for_new_user(client: AsyncClient):
    """A freshly registered user returns the column defaults: system + teal."""
    headers = await _register(client, "settings.prefs.default@example.com", "password-123")

    response = await client.get("/api/settings/preferences", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"theme": "system", "accent": "teal"}


@pytest.mark.asyncio
async def test_patch_preferences_persists_theme(client: AsyncClient):
    """PATCH theme=dark persists across subsequent GET calls."""
    headers = await _register(client, "settings.prefs.theme@example.com", "password-123")

    patch = await client.patch(
        "/api/settings/preferences",
        headers=headers,
        json={"theme": "dark"},
    )
    assert patch.status_code == 200
    assert patch.json() == {"theme": "dark", "accent": "teal"}

    fetched = await client.get("/api/settings/preferences", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == {"theme": "dark", "accent": "teal"}


@pytest.mark.asyncio
async def test_patch_preferences_persists_accent(client: AsyncClient):
    """PATCH accent=amber persists across subsequent GET calls."""
    headers = await _register(client, "settings.prefs.accent@example.com", "password-123")

    patch = await client.patch(
        "/api/settings/preferences",
        headers=headers,
        json={"accent": "amber"},
    )
    assert patch.status_code == 200
    assert patch.json() == {"theme": "system", "accent": "amber"}

    fetched = await client.get("/api/settings/preferences", headers=headers)
    assert fetched.json() == {"theme": "system", "accent": "amber"}


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_theme(client: AsyncClient):
    """An unknown theme value is rejected with 422 and the row is not mutated."""
    headers = await _register(client, "settings.prefs.badtheme@example.com", "password-123")

    response = await client.patch(
        "/api/settings/preferences",
        headers=headers,
        json={"theme": "neon"},
    )
    assert response.status_code == 422

    fetched = await client.get("/api/settings/preferences", headers=headers)
    assert fetched.json() == {"theme": "system", "accent": "teal"}


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_accent(client: AsyncClient):
    """An unknown accent value is rejected with 422."""
    headers = await _register(client, "settings.prefs.badaccent@example.com", "password-123")

    response = await client.patch(
        "/api/settings/preferences",
        headers=headers,
        json={"accent": "magenta"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_preferences_requires_auth(client: AsyncClient):
    """Unauthenticated GET /api/settings/preferences returns 401."""
    response = await client.get("/api/settings/preferences")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_preferences_requires_auth(client: AsyncClient):
    """Unauthenticated PATCH /api/settings/preferences returns 401."""
    response = await client.patch(
        "/api/settings/preferences",
        json={"theme": "dark"},
    )
    assert response.status_code == 401


# Identity (first_name, last_name) — feeds the voice-sharing directory.


@pytest.mark.asyncio
async def test_identity_defaults_empty_until_user_sets_it(client: AsyncClient):
    headers = await _register(client, "identity.default@example.com", "password-123")
    response = await client.get("/api/settings/identity", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body == {"first_name": None, "last_name": None, "has_voiceprint": False}


@pytest.mark.asyncio
async def test_patch_identity_sets_names(client: AsyncClient):
    headers = await _register(client, "identity.set@example.com", "password-123")
    response = await client.patch(
        "/api/settings/identity",
        headers=headers,
        json={"first_name": "  Mik  ", "last_name": "Wiseman"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "first_name": "Mik",
        "last_name": "Wiseman",
        "has_voiceprint": False,
    }


@pytest.mark.asyncio
async def test_patch_identity_clears_with_empty_string(client: AsyncClient):
    headers = await _register(client, "identity.clear@example.com", "password-123")
    await client.patch(
        "/api/settings/identity",
        headers=headers,
        json={"first_name": "Anna", "last_name": "Last"},
    )
    cleared = await client.patch(
        "/api/settings/identity",
        headers=headers,
        json={"first_name": ""},
    )
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["first_name"] is None
    assert body["last_name"] == "Last"


@pytest.mark.asyncio
async def test_patch_identity_rejects_too_long(client: AsyncClient):
    headers = await _register(client, "identity.long@example.com", "password-123")
    response = await client.patch(
        "/api/settings/identity",
        headers=headers,
        json={"first_name": "x" * 121},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_identity_requires_auth(client: AsyncClient):
    assert (await client.get("/api/settings/identity")).status_code == 401
    assert (
        await client.patch("/api/settings/identity", json={"first_name": "x"})
    ).status_code == 401
