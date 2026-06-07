"""Models for the user's connected third-party MCP servers (ingestion sources).

WaiComputer is already an MCP *server*; these models make it an MCP *client*:
the user connects an arbitrary MCP server (their Gmail/Calendar/Notes/finance/
time-tracking/etc.), and a Celery worker periodically pulls that server's data
(resources-first, with a read-only agentic tool fallback) into ``Item``s.

- ``McpConnection`` — one connected server per (user, server_url). Auth is a
  Fernet-encrypted blob (OAuth token set or a PAT); never stored plaintext.
  ``allowed_tools`` is a read-only allow-list (security: we never call a tool
  outside it). ``sync_cursor`` enables incremental pulls.
- ``McpIngestionRun`` — one row per sync attempt (wai-brain ``ingestion_runs``):
  idempotent retry + observability (items_in / errors / cursor before-after).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class McpConnection(Base, UUIDMixin, TimestampMixin):
    """A third-party MCP server the user has connected as an ingestion source."""

    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "server_url", name="uq_mcp_connections_user_url"),
        Index("ix_mcp_connections_user", "user_id"),
        Index("ix_mcp_connections_due", "enabled", "next_sync_at"),
        Index("ix_mcp_connections_catalog", "user_id", "catalog_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    server_label: Mapped[str] = mapped_column(String(120), nullable=False)
    server_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # streamable_http (default) | sse
    transport: Mapped[str] = mapped_column(
        String(20), nullable=False, default="streamable_http", server_default="streamable_http"
    )
    # auth_type: none | pat | oauth
    auth_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", server_default="none"
    )
    # Fernet-encrypted credential blob (PAT string or JSON OAuth token set).
    auth_secret_encrypted: Mapped[str | None] = mapped_column(Text)

    # Read-only allow-list of tool names we are permitted to call (security).
    allowed_tools: Mapped[list | None] = mapped_column(JSONB)
    # Snapshot of the server's advertised capabilities (tools/resources) at connect.
    capabilities: Mapped[dict | None] = mapped_column(JSONB)
    # Catalog provenance: which Hermes catalog entry this came from (NULL = custom),
    # a coarse source type for Brain filtering, and the resolved ingestion plan.
    catalog_id: Mapped[str | None] = mapped_column(String(64))
    source_type: Mapped[str | None] = mapped_column(String(64))
    ingest_plan: Mapped[dict | None] = mapped_column(JSONB)
    # How much history to pull on first connect (recent_30d|recent_90d|last_year|everything).
    backfill_depth: Mapped[str | None] = mapped_column(String(20))
    # Privacy class applied to every Item ingested from this connection.
    privacy_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default="internal"
    )

    sync_cursor: Mapped[str | None] = mapped_column(String(1000))
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # State machine: active | paused | needs_setup | degraded | error_transient
    #                | error_terminal. A transient error stays eligible for the
    #                beat (auto-retry with backoff); terminal stops + asks the
    #                user to reconnect — never silently disabled forever.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=false()
    )

    user: Mapped["User"] = relationship("User")
    runs: Mapped[list["McpIngestionRun"]] = relationship(
        "McpIngestionRun",
        back_populates="connection",
        cascade="all, delete-orphan",
    )


class McpIngestionRun(Base, UUIDMixin):
    """One sync attempt for a connection — idempotency + observability."""

    __tablename__ = "mcp_ingestion_runs"
    __table_args__ = (
        Index("ix_mcp_ingestion_runs_connection", "connection_id", "started_at"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    # running | succeeded | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    cursor_before: Mapped[str | None] = mapped_column(String(1000))
    cursor_after: Mapped[str | None] = mapped_column(String(1000))
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Linking observability: graph mentions written + structured-extractor
    # failures (a spike flips the connection to a visible "degraded" state).
    mentions_recorded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    extract_errors: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    extract_error_sample: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connection: Mapped["McpConnection"] = relationship("McpConnection", back_populates="runs")
