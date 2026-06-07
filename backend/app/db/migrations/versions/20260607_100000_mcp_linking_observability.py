"""MCP linking: entity identity-key index + ingestion-run extraction counters

Revision ID: 20260607_100000
Revises: 20260605_110000
Create Date: 2026-06-07 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260607_100000"
down_revision: Union[str, tuple[str, str], None] = "20260605_110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Strong-identity-key lookups: entities.metadata @> {identity_keys:[...]}
    # so resolving an emailer/handle to an existing person stays cheap at scale.
    op.create_index(
        "ix_entities_metadata_gin",
        "entities",
        ["metadata"],
        postgresql_using="gin",
    )
    # Linking observability on each sync run.
    op.add_column(
        "mcp_ingestion_runs",
        sa.Column("mentions_recorded", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mcp_ingestion_runs",
        sa.Column("extract_errors", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mcp_ingestion_runs",
        sa.Column("extract_error_sample", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_ingestion_runs", "extract_error_sample")
    op.drop_column("mcp_ingestion_runs", "extract_errors")
    op.drop_column("mcp_ingestion_runs", "mentions_recorded")
    op.drop_index("ix_entities_metadata_gin", table_name="entities")
