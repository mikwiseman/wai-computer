"""MCP catalog provenance + ingest plan + backfill depth on connections

Revision ID: 20260607_110000
Revises: 20260607_100000
Create Date: 2026-06-07 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260607_140000"
down_revision: Union[str, tuple[str, str], None] = "20260607_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mcp_connections", sa.Column("catalog_id", sa.String(length=64), nullable=True))
    op.add_column("mcp_connections", sa.Column("source_type", sa.String(length=64), nullable=True))
    op.add_column(
        "mcp_connections",
        sa.Column("ingest_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "mcp_connections", sa.Column("backfill_depth", sa.String(length=20), nullable=True)
    )
    op.create_index(
        "ix_mcp_connections_catalog", "mcp_connections", ["user_id", "catalog_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_connections_catalog", table_name="mcp_connections")
    op.drop_column("mcp_connections", "backfill_depth")
    op.drop_column("mcp_connections", "ingest_plan")
    op.drop_column("mcp_connections", "source_type")
    op.drop_column("mcp_connections", "catalog_id")
