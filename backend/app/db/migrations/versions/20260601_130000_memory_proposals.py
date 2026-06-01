"""memory_proposals (raw→valuable governance queue)

Revision ID: 20260601_130000
Revises: 20260601_120000
Create Date: 2026-06-01 13:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260601_130000"
down_revision: Union[str, None] = "20260601_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_proposals",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False,
                  server_default="memory_upsert"),
        sa.Column("risk", sa.String(length=10), nullable=False),
        sa.Column("block_label", sa.String(length=40), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_line", sa.Text(), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("authority", sa.String(length=20), nullable=False, server_default="self"),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=20), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_memory_proposals_user_dedup"),
    )
    op.create_index("ix_memory_proposals_user_id", "memory_proposals", ["user_id"])
    op.create_index(
        "ix_memory_proposals_user_status", "memory_proposals", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_proposals_user_status", table_name="memory_proposals")
    op.drop_index("ix_memory_proposals_user_id", table_name="memory_proposals")
    op.drop_table("memory_proposals")
