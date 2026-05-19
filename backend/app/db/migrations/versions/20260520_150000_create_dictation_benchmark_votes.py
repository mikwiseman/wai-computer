"""create dictation benchmark vote table

Revision ID: 20260520_150000
Revises: 20260520_140000
Create Date: 2026-05-20 15:00:00.000000+00:00
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260520_150000"
down_revision: Union[str, None] = "20260520_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictation_benchmark_votes",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("battle_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("selected_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("selected_provider", sa.String(length=40), nullable=False),
        sa.Column("selected_model", sa.String(length=100), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dictation_benchmark_votes_battle_id"),
        "dictation_benchmark_votes",
        ["battle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dictation_benchmark_votes_user_id"),
        "dictation_benchmark_votes",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dictation_benchmark_votes_user_id"), table_name="dictation_benchmark_votes")
    op.drop_index(op.f("ix_dictation_benchmark_votes_battle_id"), table_name="dictation_benchmark_votes")
    op.drop_table("dictation_benchmark_votes")
