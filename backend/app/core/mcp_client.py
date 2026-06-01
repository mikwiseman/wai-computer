"""Thin async client for talking to a third-party MCP server (ingestion side).

Wraps the official ``mcp`` SDK (``streamablehttp_client`` + ``ClientSession``)
behind a tiny, mockable surface:

- ``introspect()`` -> what the server offers (tool names + resource list).
- ``list_resources()`` / ``read_resource(uri)`` -> the resources-first data pull.
- ``call_tool(name, args)`` -> the read-only agentic fallback (callers MUST
  pass only allow-listed tool names; enforcement lives in the orchestrator).

A bearer token (PAT or OAuth access token) is sent via the Authorization
header. All network/SDK use is isolated here so the ingestion orchestrator is
unit-testable against a fake client.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Caps so a hostile/buggy server can't exhaust us (defense-in-depth).
MAX_RESOURCES_PER_SYNC = 200
MAX_RESOURCE_BYTES = 2_000_000  # 2 MB per resource


@dataclass
class McpResource:
    uri: str
    name: str | None = None
    description: str | None = None
    mime_type: str | None = None


@dataclass
class McpIntrospection:
    tools: list[str] = field(default_factory=list)
    resources: list[McpResource] = field(default_factory=list)


@asynccontextmanager
async def _open_session(server_url: str, token: str | None):
    """Open an initialized MCP ClientSession over Streamable HTTP."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(server_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


class McpClient:
    """Connect to one third-party MCP server and pull data."""

    def __init__(self, server_url: str, token: str | None = None):
        self.server_url = server_url
        self.token = token

    async def introspect(self) -> McpIntrospection:
        async with _open_session(self.server_url, self.token) as session:
            tools_result = await session.list_tools()
            tool_names = [t.name for t in getattr(tools_result, "tools", [])]
            resources: list[McpResource] = []
            try:
                res_result = await session.list_resources()
                for r in getattr(res_result, "resources", []):
                    resources.append(
                        McpResource(
                            uri=str(r.uri),
                            name=getattr(r, "name", None),
                            description=getattr(r, "description", None),
                            mime_type=getattr(r, "mimeType", None),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 — server may not support resources
                logger.info("mcp introspect: resources unavailable (%s)", type(exc).__name__)
            return McpIntrospection(tools=tool_names, resources=resources)

    async def list_resources(self) -> list[McpResource]:
        async with _open_session(self.server_url, self.token) as session:
            res_result = await session.list_resources()
            return [
                McpResource(
                    uri=str(r.uri),
                    name=getattr(r, "name", None),
                    description=getattr(r, "description", None),
                    mime_type=getattr(r, "mimeType", None),
                )
                for r in getattr(res_result, "resources", [])
            ][:MAX_RESOURCES_PER_SYNC]

    async def read_resource(self, uri: str) -> str:
        """Read a resource's text content (concatenated text parts)."""
        async with _open_session(self.server_url, self.token) as session:
            result = await session.read_resource(uri)
            return _resource_text(result)

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Call a (caller-allow-listed) read-only tool; return its text output."""
        async with _open_session(self.server_url, self.token) as session:
            result = await session.call_tool(name, args)
            return _tool_text(result)


def _resource_text(result: Any) -> str:
    """Extract text from a read_resource result (mcp ReadResourceResult)."""
    parts: list[str] = []
    for content in getattr(result, "contents", []) or []:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            parts.append(text)
    joined = "\n".join(parts)
    return joined[:MAX_RESOURCE_BYTES]


def _tool_text(result: Any) -> str:
    """Extract text from a call_tool result (mcp CallToolResult)."""
    parts: list[str] = []
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            parts.append(text)
    joined = "\n".join(parts)
    return joined[:MAX_RESOURCE_BYTES]
