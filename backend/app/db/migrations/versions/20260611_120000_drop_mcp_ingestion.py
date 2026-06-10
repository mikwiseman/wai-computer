"""Drop MCP ingestion connector tables.

The MCP *client* connectors (Gmail/Slack/Notion/... sources synced into items)
were removed from the product. The MCP *server* (``/mcp`` endpoint + OAuth
tables) is unaffected. Items previously synced from connectors remain plain
items; their ``source`` string column keeps historical provenance.

Revision ID: 20260611_120000
Revises: 20260610_150000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_120000"
down_revision: Union[str, tuple[str, str], None] = "20260610_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_mcp_ingestion_runs_connection", table_name="mcp_ingestion_runs")
    op.drop_table("mcp_ingestion_runs")
    op.drop_index("ix_mcp_connections_catalog", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_due", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_user", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_user_id", table_name="mcp_connections")
    op.drop_table("mcp_connections")


def downgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("server_label", sa.String(length=120), nullable=False),
        sa.Column("server_url", sa.String(length=2000), nullable=False),
        sa.Column(
            "transport",
            sa.String(length=20),
            nullable=False,
            server_default="streamable_http",
        ),
        sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("auth_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column(
            "privacy_level",
            sa.String(length=20),
            nullable=False,
            server_default="standard",
        ),
        sa.Column("sync_cursor", sa.String(length=1000), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("catalog_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("ingest_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("backfill_depth", sa.String(length=20), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mcp_connections_user_id", "mcp_connections", ["user_id"])
    op.create_index("ix_mcp_connections_user", "mcp_connections", ["user_id"])
    op.create_index("ix_mcp_connections_due", "mcp_connections", ["enabled", "next_sync_at"])
    op.create_index("ix_mcp_connections_catalog", "mcp_connections", ["user_id", "catalog_id"])

    op.create_table(
        "mcp_ingestion_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("cursor_before", sa.String(length=1000), nullable=True),
        sa.Column("cursor_after", sa.String(length=1000), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mentions_recorded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extract_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "extract_error_sample",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mcp_ingestion_runs_connection",
        "mcp_ingestion_runs",
        ["connection_id", "started_at"],
    )
