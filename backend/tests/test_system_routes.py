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
async def test_self_host_provision_accepts_vps_ip_without_public_domain(
    client,
    auth_headers,
) -> None:
    response = await client.post(
        "/api/self-host/provision",
        headers=auth_headers,
        json={
            "vps_ip": "203.0.113.10",
            "ssh_username": "root",
            "auth_method": "password",
            "ssh_password": "temporary-bootstrap-password",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["hostname"] is None
    assert payload["vps_ip"] == "203.0.113.10"
    assert payload["steps"][0]["label"] == "Validate VPS address and SSH access"
    assert "temporary-bootstrap-password" not in response.text


@pytest.mark.asyncio
async def test_self_host_provision_validation_does_not_echo_password(
    client,
    auth_headers,
) -> None:
    response = await client.post(
        "/api/self-host/provision",
        headers=auth_headers,
        json={
            "hostname": "demo.self.wai.computer",
            "vps_ip": "203.0.113.10",
            "ssh_username": "root",
            "auth_method": "ssh_key",
            "ssh_password": "super-secret-bootstrap-password",
        },
    )

    assert response.status_code == 422
    assert "super-secret-bootstrap-password" not in response.text


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
async def test_self_host_migration_contract_describes_agent_data_and_exclusions(
    client,
    auth_headers,
) -> None:
    response = await client.get("/api/self-host/migration/contract", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "2026-06-03"
    assert payload["archive_format"] == "wai-self-host-export-v1"
    assert payload["preserve_user_ids"] is True
    assert payload["collision_policy"] == "reject"
    owned_tables = {row["table"]: row for row in payload["owned_exportable"]["tables"]}
    excluded_tables = {row["table"] for row in payload["excluded"]["tables"]}
    reconnect_tables = {row["table"] for row in payload["reconnect_required"]["tables"]}
    assert owned_tables["agents"]["scope_strategy"] == "owner_scoped_user_id"
    assert owned_tables["agents"]["contains_user_content"] is True
    assert owned_tables["agent_runs"]["scope_strategy"] == "owner_scoped_user_id"
    assert owned_tables["agent_runs"]["contains_user_content"] is True
    assert owned_tables["agent_steps"]["scope_strategy"] == "derived_owner_scoped"
    assert owned_tables["agent_steps"]["contains_user_content"] is True
    assert owned_tables["agent_steps"]["derived_owner_edge"] == {
        "parent_table": "agent_runs",
        "local_column": "run_id",
        "parent_column": "id",
        "owner_column": "user_id",
    }
    assert "billing_plans" in excluded_tables
    assert "refresh_tokens" in reconnect_tables


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
