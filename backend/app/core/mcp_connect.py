"""One-tap agent-connect builders for the WaiComputer MCP server (P0c).

Pure, dependency-free functions that turn a freshly-minted scoped token + the
canonical ``/mcp`` URL into copy-paste-ready connect material for each supported
client: a config snippet, an OS deeplink, and/or a one-line install command.

Security boundary (see m56/m57): a token is a secret. OS deeplinks (Cursor /
VS Code) carry the **URL only** and rely on OAuth — never the bearer token in a
clickable link. Token-bearing material (OpenClaw / Hermes / Claude Code / Codex /
generic JSON) is meant for the user to paste into a *local* config or terminal,
where embedding the just-minted PAT is acceptable. The actual mint + server-side
smoke-test live in the route layer; this module is pure string assembly so it is
trivially unit-testable.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import quote

SERVER_KEY = "waicomputer"
_AUTH_HEADER = "Authorization"


@dataclass(frozen=True)
class ConnectClient:
    """A connectable agent/host and how it prefers to be wired."""

    id: str
    name: str
    # "oauth" -> connect by URL + OAuth (no token); "pat" -> paste a bearer
    # token; "both" -> either works (token is the low-friction default here).
    auth: str
    supports_deeplink: bool
    docs_url: str | None = None


# Order = display order in the connect grid. OpenClaw + Hermes first: they are the
# headline targets (Garry-style agent brains) and they have no OS deeplink, so
# their flow is one-tap-provision + one-paste.
CLIENTS: tuple[ConnectClient, ...] = (
    ConnectClient("openclaw", "OpenClaw", "pat", False, "https://openclaw.ai/docs/mcp"),
    ConnectClient("hermes", "Hermes", "pat", False, "https://github.com/NousResearch/hermes"),
    ConnectClient("cursor", "Cursor", "oauth", True, "https://docs.cursor.com/context/mcp"),
    ConnectClient("vscode", "VS Code", "oauth", True, "https://code.visualstudio.com/docs/copilot/mcp"),
    ConnectClient("claude", "Claude.ai", "oauth", False, "https://support.anthropic.com/en/articles/connectors"),
    ConnectClient("chatgpt", "ChatGPT", "oauth", False, "https://platform.openai.com/docs/mcp"),
    ConnectClient("claude-code", "Claude Code", "pat", False, "https://docs.claude.com/claude-code/mcp"),
    ConnectClient("codex", "Codex CLI", "pat", False, "https://github.com/openai/codex"),
    ConnectClient("custom", "Other / custom", "both", False, None),
)

_BY_ID = {c.id: c for c in CLIENTS}


def get_client(client_id: str) -> ConnectClient | None:
    return _BY_ID.get(client_id)


def clients_catalog() -> list[dict]:
    """Catalog for the connect grid — one source of truth across web/Mac/iOS."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "auth": c.auth,
            "supports_deeplink": c.supports_deeplink,
            "docs_url": c.docs_url,
        }
        for c in CLIENTS
    ]


def _mcp_servers_json(mcp_url: str, token: str | None) -> dict:
    """The de-facto-standard ``mcpServers`` object many clients accept."""
    server: dict = {"url": mcp_url}
    if token:
        server["headers"] = {_AUTH_HEADER: f"Bearer {token}"}
    return {"mcpServers": {SERVER_KEY: server}}


def build_connect_config(client_id: str, mcp_url: str, token: str | None) -> str:
    """A copy-paste config block for ``client_id``.

    Token is embedded only for PAT-style local clients; OAuth clients get a
    token-free block (the client runs OAuth on connect).
    """
    client = get_client(client_id)
    embed = token if (client is None or client.auth in ("pat", "both")) else None

    if client_id == "hermes":
        # Hermes config.yaml: register the server AND wire it as the memory
        # provider so it auto-recalls every turn.
        auth_line = f'\n      {_AUTH_HEADER}: "Bearer {token}"' if token else ""
        return (
            "mcp_servers:\n"
            f"  {SERVER_KEY}:\n"
            f"    url: {mcp_url}\n"
            f"    headers:{auth_line}\n"
            "memory:\n"
            f"  provider: {SERVER_KEY}\n"
        )

    return json.dumps(_mcp_servers_json(mcp_url, embed), indent=2)


def build_deeplink(client_id: str, mcp_url: str) -> str | None:
    """An OS deeplink that opens the client with the server prefilled (OAuth).

    Never embeds a token — the client authorizes via OAuth on open. Returns
    ``None`` for clients without a deeplink.
    """
    server_obj = {"url": mcp_url}
    if client_id == "cursor":
        cfg = base64.b64encode(json.dumps(server_obj).encode()).decode()
        return f"cursor://anysphere.cursor-deeplink/mcp/install?name={SERVER_KEY}&config={cfg}"
    if client_id == "vscode":
        payload = {"name": SERVER_KEY, **server_obj}
        return f"vscode:mcp/install?{quote(json.dumps(payload))}"
    return None


def build_install_command(client_id: str, mcp_url: str, token: str | None) -> str | None:
    """A one-line terminal install command (PAT clients), or ``None``.

    Includes a verify step where the client supports one, so a bad token fails
    at setup rather than silently mid-chat.
    """
    bearer = f'"Bearer {token}"' if token else '"Bearer <YOUR_TOKEN>"'
    if client_id == "openclaw":
        return (
            f"openclaw mcp add {SERVER_KEY} --url {mcp_url} "
            f"--header {_AUTH_HEADER}:{bearer} && openclaw mcp doctor {SERVER_KEY}"
        )
    if client_id == "claude-code":
        return (
            f"claude mcp add --transport http {SERVER_KEY} {mcp_url} "
            f"--header {_AUTH_HEADER}:{bearer}"
        )
    if client_id == "codex":
        # Codex reads the bearer from the environment at runtime, never config.
        return (
            f'export WAICOMPUTER_MCP_TOKEN={token or "<YOUR_TOKEN>"} && '
            f"codex mcp add {SERVER_KEY} --url {mcp_url} "
            f'--header {_AUTH_HEADER}:"Bearer $WAICOMPUTER_MCP_TOKEN"'
        )
    return None


def build_connect_material(client_id: str, mcp_url: str, token: str | None) -> dict:
    """Everything the UI needs to render a client's connect card."""
    client = get_client(client_id)
    return {
        "client": client_id,
        "name": client.name if client else client_id,
        "auth": client.auth if client else "both",
        "mcp_url": mcp_url,
        "config": build_connect_config(client_id, mcp_url, token),
        "deeplink": build_deeplink(client_id, mcp_url),
        "install_command": build_install_command(client_id, mcp_url, token),
        "docs_url": client.docs_url if client else None,
    }
