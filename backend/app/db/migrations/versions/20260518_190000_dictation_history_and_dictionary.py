"""create dictation_entries and dictation_dictionary_words tables

Revision ID: 20260518_190000
Revises: 20260518_175000
Create Date: 2026-05-18 19:00:00.000000+00:00

Backs the macOS client's local dictation log + custom vocabulary with a
server-side store so history survives logout/login and syncs across Macs.
`client_*_id` is the client-generated UUID used for idempotent POSTs.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260518_190000"
down_revision: Union[str, None] = "20260518_175000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictation_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("cleaned_text", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=False),
        sa.Column("word_count", sa.Integer, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint(
            "user_id", "client_entry_id", name="uq_dictation_entries_user_client_id"
        ),
    )
    op.create_index(
        "ix_dictation_entries_user_id",
        "dictation_entries",
        ["user_id"],
    )
    op.create_index(
        "ix_dictation_entries_occurred_at",
        "dictation_entries",
        ["occurred_at"],
    )

    op.create_table(
        "dictation_dictionary_words",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_word_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("word", sa.String(200), nullable=False),
        sa.Column("replacement", sa.String(200), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint(
            "user_id", "client_word_id", name="uq_dictation_dictionary_user_client_id"
        ),
    )
    op.create_index(
        "ix_dictation_dictionary_words_user_id",
        "dictation_dictionary_words",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dictation_dictionary_words_user_id", "dictation_dictionary_words"
    )
    op.drop_table("dictation_dictionary_words")

    op.drop_index("ix_dictation_entries_occurred_at", "dictation_entries")
    op.drop_index("ix_dictation_entries_user_id", "dictation_entries")
    op.drop_table("dictation_entries")
