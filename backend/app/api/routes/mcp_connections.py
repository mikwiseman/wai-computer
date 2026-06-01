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

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.secrets_crypto import encrypt_secret
from app.models.mcp_connection import McpConnection

router = APIRouter(prefix="/mcp-connections", tags=["mcp-connections"])


class CreateConnectionRequest(BaseModel):
    server_label: str = Field(min_length=1, max_length=120)
    server_url: str = Field(min_length=1, max_length=2000)
    transport: str = Field(default="streamable_http", max_length=20)
    auth_type: str = Field(default="none", max_length=20)  # none | pat | oauth
    auth_token: str | None = None  # PAT or OAuth access token (write-only)
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)
    privacy_level: str = Field(default="internal", max_length=20)


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


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    request: CreateConnectionRequest,
    user: CurrentUser,
    db: Database,
) -> ConnectionResponse:
    """Connect a third-party MCP server. Token is encrypted; server introspected."""
    if request.auth_type != "none" and not (request.auth_token or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auth_token is required for the selected auth_type.",
        )

    existing = (
        await db.execute(
            select(McpConnection).where(
                McpConnection.user_id == user.id,
                McpConnection.server_url == request.server_url,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That server is already connected.",
        )

    conn = McpConnection(
        user_id=user.id,
        server_label=request.server_label,
        server_url=request.server_url,
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
    db.add(conn)
    await db.flush()

    # Best-effort introspection so the UI can show what the server offers.
    try:
        from app.core.mcp_client import McpClient
        from app.core.secrets_crypto import decrypt_secret

        token = (
            decrypt_secret(conn.auth_secret_encrypted)
            if conn.auth_secret_encrypted
            else None
        )
        intro = await McpClient(conn.server_url, token).introspect()
        conn.capabilities = {
            "tools": intro.tools,
            "resource_count": len(intro.resources),
        }
        conn.allowed_tools = []  # default: no tools allowed (resources-only)
        await db.flush()
    except Exception:  # noqa: BLE001 — connection is saved; introspection can retry on sync
        conn.last_error = "introspection_pending"
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
    except Exception:  # noqa: BLE001 — broker optional
        pass
    return {"status": "queued", "connection_id": str(conn.id)}


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID, user: CurrentUser, db: Database
) -> None:
    conn = await _get_owned(db, user, connection_id)
    await db.delete(conn)
