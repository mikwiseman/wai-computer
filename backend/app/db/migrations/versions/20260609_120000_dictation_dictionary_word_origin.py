"""add origin column to dictation_dictionary_words

Revision ID: 20260609_120000
Revises: 20260608_120000
Create Date: 2026-06-09 12:00:00.000000+00:00

Marks how a dictionary word was created: ``manual`` (the user typed it) or
``learned`` (auto-suggested from the user's edits, then accepted). Clients
render learned words with a ✨ marker; the column syncs across Macs. Existing
rows default to ``manual`` so nothing is silently re-labelled.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_120000"
down_revision: Union[str, None] = "20260608_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dictation_dictionary_words",
        sa.Column(
            "origin",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("dictation_dictionary_words", "origin")
