"""add dictation snippets table

Revision ID: 20260707_213000
Revises: 20260707_210000
Create Date: 2026-07-07 21:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260707_213000"
down_revision: Union[str, tuple[str, str], None] = "20260707_210000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictation_snippets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_snippet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=120), nullable=False),
        sa.Column("expansion", sa.String(length=4000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "client_snippet_id", name="uq_dictation_snippets_user_client_id"
        ),
    )
    op.create_index(
        "ix_dictation_snippets_user_id", "dictation_snippets", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_dictation_snippets_user_id", table_name="dictation_snippets")
    op.drop_table("dictation_snippets")
