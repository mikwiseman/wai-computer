"""live brain maps

Revision ID: 20260605_100000
Revises: 20260605_090000
Create Date: 2026-06-05 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_100000"
down_revision: Union[str, None] = "20260605_090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brain_maps",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("map_type", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=40), server_default="brain", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("source_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brain_maps_space", "brain_maps", ["space_id"], unique=False)
    op.create_index(
        "ix_brain_maps_user_status", "brain_maps", ["user_id", "status"], unique=False
    )
    op.create_index(
        "ix_brain_maps_user_updated", "brain_maps", ["user_id", "updated_at"], unique=False
    )

    op.create_table(
        "brain_map_revisions",
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_index", sa.Integer(), nullable=False),
        sa.Column("projection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("freshness", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["map_id"], ["brain_maps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("map_id", "revision_index", name="uq_brain_map_revisions_map_idx"),
    )
    op.create_index(
        "ix_brain_map_revisions_fingerprint",
        "brain_map_revisions",
        ["map_id", "source_fingerprint"],
        unique=False,
    )
    op.create_index("ix_brain_map_revisions_map", "brain_map_revisions", ["map_id"])
    op.create_index(
        "ix_brain_map_revisions_user_compiled",
        "brain_map_revisions",
        ["user_id", "compiled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_brain_map_revisions_user_compiled", table_name="brain_map_revisions")
    op.drop_index("ix_brain_map_revisions_map", table_name="brain_map_revisions")
    op.drop_index("ix_brain_map_revisions_fingerprint", table_name="brain_map_revisions")
    op.drop_table("brain_map_revisions")
    op.drop_index("ix_brain_maps_user_updated", table_name="brain_maps")
    op.drop_index("ix_brain_maps_user_status", table_name="brain_maps")
    op.drop_index("ix_brain_maps_space", table_name="brain_maps")
    op.drop_table("brain_maps")
