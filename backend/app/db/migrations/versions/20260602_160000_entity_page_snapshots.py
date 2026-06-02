"""entity page snapshots

Revision ID: 20260602_160000
Revises: 20260602_150000
Create Date: 2026-06-02 16:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260602_160000"
down_revision: Union[str, None] = "20260602_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_page_snapshots",
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
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("timeline", postgresql.JSONB(), nullable=False),
        sa.Column("related_explanations", postgresql.JSONB(), nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column(
            "compiled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
        sa.UniqueConstraint("entity_id", name="uq_entity_page_snapshots_entity"),
    )
    op.create_index(
        "ix_entity_page_snapshots_user_id", "entity_page_snapshots", ["user_id"]
    )
    op.create_index(
        "ix_entity_page_snapshots_entity_id", "entity_page_snapshots", ["entity_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_entity_page_snapshots_entity_id", table_name="entity_page_snapshots")
    op.drop_index("ix_entity_page_snapshots_user_id", table_name="entity_page_snapshots")
    op.drop_table("entity_page_snapshots")
