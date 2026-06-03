"""System/self-host route contract tests."""

from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_resolves_public_base_url_for_self_host() -> None:
    settings = Settings(
        jwt_secret="secret",
        frontend_url="https://wai.computer",
        public_base_url="https://demo.self.wai.computer",
        deployment_mode="self_host",
    )

    assert settings.public_base_url_resolved == "https://demo.self.wai.computer"
    assert settings.mcp_resource_url_resolved == "https://demo.self.wai.computer/mcp"


@pytest.mark.asyncio
async def test_system_info_route(client) -> None:
    response = await client.get("/api/system/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app_name"] == "WaiComputer"
    assert payload["deployment_mode"] in {"wai_cloud", "self_host", "provisioning"}
    assert payload["public_base_url"]
    assert payload["mcp_url"].endswith("/mcp")
    assert payload["audio_retention_policy"] == "delete_after_processing"


@pytest.mark.asyncio
async def test_self_host_provision_rejects_invalid_ip(client, auth_headers) -> None:
    response = await client.post(
        "/api/self-host/provision",
        headers=auth_headers,
        json={
            "hostname": "demo.self.wai.computer",
            "vps_ip": "not-an-ip",
            "ssh_username": "root",
            "auth_method": "ssh_key",
            "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest demo",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_self_host_migration_preflight_groups_owned_and_reconnect_data(
    client,
    auth_headers,
) -> None:
    response = await client.get("/api/self-host/migration/preflight", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert "recordings" in payload["owned_exportable"]
    assert "document_uploads" in payload["owned_exportable"]
    assert "refresh_tokens" in payload["reconnect_required"]
    assert "recording_audio_staging" in payload["server_local"]
    assert payload["data_map"]["audio_retention_policy"] == "delete_after_processing"


@pytest.mark.asyncio
async def test_self_host_provision_surfaces_manual_review_status(client, auth_headers) -> None:
    response = await client.post(
        "/api/self-host/provision",
        headers=auth_headers,
        json={
            "hostname": "demo.self.wai.computer",
            "vps_ip": "203.0.113.10",
            "ssh_username": "root",
            "auth_method": "ssh_key",
            "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest demo",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "manual_review_required"
    assert payload["steps"][0]["id"] == "validate_inputs"
    assert payload["steps"][-1]["id"] == "remove_bootstrap_access"
