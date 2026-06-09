"""Unit tests for the one-tap agent-connect builders (P0c). Pure functions —
no DB, no network."""

import base64
import json
from urllib.parse import unquote

from app.core.mcp_connect import (
    build_connect_config,
    build_connect_material,
    build_deeplink,
    build_install_command,
    clients_catalog,
)

MCP = "https://wai.computer/mcp"
TOK = "wc_live_secrettoken123"


def test_catalog_includes_headline_clients() -> None:
    ids = {c["id"] for c in clients_catalog()}
    assert {"openclaw", "hermes", "cursor", "vscode"} <= ids


def test_openclaw_config_embeds_token() -> None:
    server = json.loads(build_connect_config("openclaw", MCP, TOK))["mcpServers"]["waicomputer"]
    assert server["url"] == MCP
    assert server["headers"]["Authorization"] == f"Bearer {TOK}"


def test_hermes_config_is_yaml_with_memory_provider() -> None:
    cfg = build_connect_config("hermes", MCP, TOK)
    assert "mcp_servers:" in cfg
    assert "provider: waicomputer" in cfg  # auto-recall every turn
    assert TOK in cfg


def test_oauth_client_config_omits_token() -> None:
    # Claude.ai connects via OAuth — the bearer must never be in its config block.
    assert TOK not in build_connect_config("claude", MCP, TOK)


def test_cursor_deeplink_carries_url_not_token() -> None:
    link = build_deeplink("cursor", MCP)
    assert link.startswith("cursor://")
    decoded = json.loads(base64.b64decode(link.split("config=", 1)[1]))
    assert decoded["url"] == MCP
    assert TOK not in link  # security: never embed a token in a clickable link


def test_vscode_deeplink() -> None:
    link = build_deeplink("vscode", MCP)
    assert link.startswith("vscode:mcp/install?")
    payload = json.loads(unquote(link.split("?", 1)[1]))
    assert payload["url"] == MCP


def test_no_deeplink_for_terminal_clients() -> None:
    assert build_deeplink("openclaw", MCP) is None
    assert build_deeplink("hermes", MCP) is None


def test_openclaw_install_command_has_verify_step() -> None:
    cmd = build_install_command("openclaw", MCP, TOK)
    assert "openclaw mcp add" in cmd
    assert "doctor" in cmd  # smoke-test on the user's machine
    assert TOK in cmd


def test_codex_reads_token_from_env_not_config() -> None:
    cmd = build_install_command("codex", MCP, TOK)
    assert "WAICOMPUTER_MCP_TOKEN" in cmd


def test_connect_material_shape() -> None:
    mat = build_connect_material("openclaw", MCP, TOK)
    assert mat["client"] == "openclaw"
    assert mat["mcp_url"] == MCP
    assert mat["config"]
    assert mat["install_command"]
    assert mat["deeplink"] is None
    assert mat["auth"] == "pat"
