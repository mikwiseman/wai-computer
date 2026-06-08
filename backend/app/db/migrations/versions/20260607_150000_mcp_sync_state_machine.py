"""MCP connection sync state machine + freshness columns

Revision ID: 20260607_120000
Revises: 20260607_110000
Create Date: 2026-06-07 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260607_150000"
down_revision: Union[str, tuple[str, str], None] = "20260607_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mcp_connections",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mcp_connections", sa.Column("last_error_code", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "mcp_connections",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "last_error_at")
    op.drop_column("mcp_connections", "last_error_code")
    op.drop_column("mcp_connections", "consecutive_failures")
    op.drop_column("mcp_connections", "last_success_at")
