"""Routes to connect / manage third-party MCP servers as ingestion sources.

POST   /mcp-connections            connect a server (encrypts token, introspects)
GET    /mcp-connections            list the user's connections (no secrets)
GET    /mcp-connections/{id}        one connection
POST   /mcp-connections/{id}/sync   trigger an immediate sync
PATCH  /mcp-connections/{id}        pause/resume / change interval
DELETE /mcp-connections/{id}        disconnect

The auth token is Fernet-encrypted at rest and never returned in any response.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.secrets_crypto import encrypt_secret
from app.models.mcp_connection import McpConnection

router = APIRouter(prefix="/mcp-connections", tags=["mcp-connections"])

VALID_MCP_TRANSPORTS = {"streamable_http"}
VALID_MCP_AUTH_TYPES = {"none", "pat", "oauth"}
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}


class CreateConnectionRequest(BaseModel):
    server_label: str = Field(min_length=1, max_length=120)
    server_url: str = Field(min_length=1, max_length=2000)
    transport: str = Field(default="streamable_http", max_length=20)
    auth_type: str = Field(default="none", max_length=20)  # none | pat | oauth
    auth_token: str | None = None  # PAT or OAuth access token (write-only)
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)
    privacy_level: str = Field(default="internal", max_length=20)

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_MCP_TRANSPORTS:
            raise ValueError(
                f"transport must be one of: {', '.join(sorted(VALID_MCP_TRANSPORTS))}"
            )
        return normalized

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_MCP_AUTH_TYPES:
            raise ValueError(
                f"auth_type must be one of: {', '.join(sorted(VALID_MCP_AUTH_TYPES))}"
            )
        return normalized


class UpdateConnectionRequest(BaseModel):
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    server_label: str | None = Field(default=None, max_length=120)


class ConnectionResponse(BaseModel):
    id: str
    server_label: str
    server_url: str
    transport: str
    auth_type: str
    has_token: bool
    allowed_tools: list | None
    capabilities: dict | None
    privacy_level: str
    sync_interval_minutes: int
    status: str
    enabled: bool
    last_sync_at: str | None
    last_error: str | None
    created_at: str


def _response(c: McpConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=str(c.id),
        server_label=c.server_label,
        server_url=c.server_url,
        transport=c.transport,
        auth_type=c.auth_type,
        has_token=bool(c.auth_secret_encrypted),
        allowed_tools=c.allowed_tools,
        capabilities=c.capabilities,
        privacy_level=c.privacy_level,
        sync_interval_minutes=c.sync_interval_minutes,
        status=c.status,
        enabled=c.enabled,
        last_sync_at=c.last_sync_at.isoformat() if c.last_sync_at else None,
        last_error=c.last_error,
        created_at=c.created_at.isoformat(),
    )


async def _get_owned(db, user, connection_id: UUID) -> McpConnection:
    conn = (
        await db.execute(
            select(McpConnection).where(
                McpConnection.id == connection_id,
                McpConnection.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return conn


def _validate_safe_mcp_server_url(server_url: str) -> str:
    value = server_url.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server_url must be an HTTPS URL.",
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server_url must not include credentials.",
        )
    hostname = parsed.hostname.strip().lower()
    if hostname in LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server_url must not target local hosts.",
        )
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return value
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server_url must not target private or local networks.",
        )
    return value


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    request: CreateConnectionRequest,
    user: CurrentUser,
    db: Database,
) -> ConnectionResponse:
    """Connect a third-party MCP server. Token is encrypted; server introspected."""
    server_url = _validate_safe_mcp_server_url(request.server_url)
    if request.auth_type != "none" and not (request.auth_token or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auth_token is required for the selected auth_type.",
        )

    existing = (
        await db.execute(
            select(McpConnection).where(
                McpConnection.user_id == user.id,
                McpConnection.server_url == server_url,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That server is already connected.",
        )

    try:
        from app.core.mcp_client import McpClient

        token = request.auth_token if request.auth_type != "none" else None
        intro = await McpClient(server_url, token).introspect()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MCP server introspection failed.",
        ) from exc

    conn = McpConnection(
        user_id=user.id,
        server_label=request.server_label,
        server_url=server_url,
        transport=request.transport,
        auth_type=request.auth_type,
        auth_secret_encrypted=(
            encrypt_secret(request.auth_token)
            if request.auth_type != "none" and request.auth_token
            else None
        ),
        privacy_level=request.privacy_level,
        sync_interval_minutes=request.sync_interval_minutes,
        enabled=True,
        next_sync_at=datetime.now(timezone.utc),  # sync ASAP on next beat
    )
    conn.capabilities = {
        "tools": intro.tools,
        "resource_count": len(intro.resources),
    }
    conn.allowed_tools = []  # default: no tools allowed (resources-only)
    db.add(conn)
    await db.flush()

    return _response(conn)


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    user: CurrentUser,
    db: Database,
    limit: int = Query(100, ge=1, le=200),
) -> list[ConnectionResponse]:
    rows = (
        await db.execute(
            select(McpConnection)
            .where(McpConnection.user_id == user.id)
            .order_by(McpConnection.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_response(c) for c in rows]


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID, user: CurrentUser, db: Database
) -> ConnectionResponse:
    return _response(await _get_owned(db, user, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: UUID,
    request: UpdateConnectionRequest,
    user: CurrentUser,
    db: Database,
) -> ConnectionResponse:
    conn = await _get_owned(db, user, connection_id)
    if request.enabled is not None:
        conn.enabled = request.enabled
        conn.status = "active" if request.enabled else "paused"
    if request.sync_interval_minutes is not None:
        conn.sync_interval_minutes = request.sync_interval_minutes
    if request.server_label is not None:
        conn.server_label = request.server_label
    await db.flush()
    return _response(conn)


@router.post("/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(
    connection_id: UUID, user: CurrentUser, db: Database
) -> dict[str, str]:
    conn = await _get_owned(db, user, connection_id)
    if not conn.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Connection is paused."
        )
    try:
        from app.tasks.mcp_sync import sync_mcp_connection

        sync_mcp_connection.delay(connection_id=str(conn.id))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue MCP sync.",
        ) from exc
    return {"status": "queued", "connection_id": str(conn.id)}


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_connection(
    connection_id: UUID, user: CurrentUser, db: Database
) -> Response:
    conn = await _get_owned(db, user, connection_id)
    await db.delete(conn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
