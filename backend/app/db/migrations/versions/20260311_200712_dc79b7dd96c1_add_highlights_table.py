"""add highlights table

Revision ID: dc79b7dd96c1
Revises: 000006
Create Date: 2026-03-11 20:07:12.119614+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "dc79b7dd96c1"
down_revision: Union[str, None] = "000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "highlights",
        sa.Column("recording_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("speaker", sa.String(length=100), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("importance", sa.String(length=10), nullable=False),
        sa.Column(
            "source_segment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["recordings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_highlights_recording_id"),
        "highlights",
        ["recording_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_highlights_recording_id"), table_name="highlights")
    op.drop_table("highlights")
