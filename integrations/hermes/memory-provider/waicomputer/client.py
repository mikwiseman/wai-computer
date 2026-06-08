"""Tiny MCP-over-HTTP client for WaiComputer's remote MCP server.

WaiComputer exposes a Streamable-HTTP MCP server at ``{base_url}/mcp``. We only
need to call four tools (ask / search / remember / fetch), so rather than pull
in a full MCP SDK we speak the JSON-RPC ``tools/call`` method directly with a
static ``wc_live_`` Bearer token. The server replies with either JSON or an SSE
``data:`` frame; we handle both.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

_ACCEPT = "application/json, text/event-stream"


class WaiComputerError(RuntimeError):
    """A WaiComputer MCP tool returned an error (e.g. read-only connection)."""


class WaiComputerClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0) -> None:
        self._url = base_url.rstrip("/") + "/mcp"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": _ACCEPT,
            "Content-Type": "application/json",
        }
        self._http = httpx.Client(timeout=timeout)
        self._id = 0

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        resp = self._http.post(
            self._url,
            headers=self._headers,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
        )
        resp.raise_for_status()
        body = resp.text
        if "data:" in body and not body.lstrip().startswith("{"):
            for line in body.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
        return resp.json()

    def _tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}).get("result", {})
        text = (result.get("content") or [{}])[0].get("text", "")
        if result.get("isError"):
            raise WaiComputerError(text or f"{name} failed")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    # --- the four brain tools -------------------------------------------------

    def ask(self, question: str) -> dict[str, Any]:
        """One cited answer synthesised across recordings, notes, and chats."""
        return self._tool("ask", {"question": question})

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Unified search across the whole brain."""
        return self._tool("search", {"query": query, "limit": limit})

    def fetch(self, document_id: str) -> dict[str, Any]:
        """Open one recording / note / chat by id."""
        return self._tool("fetch", {"id": document_id})

    def remember(
        self, text: str, title: str | None = None, source_url: str | None = None
    ) -> dict[str, Any]:
        """Save a new memory (raises WaiComputerError if the token is read-only)."""
        args: dict[str, Any] = {"text": text}
        if title:
            args["title"] = title
        if source_url:
            args["source_url"] = source_url
        return self._tool("remember", args)

    def close(self) -> None:
        self._http.close()
