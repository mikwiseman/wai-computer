"""add missing server defaults to dictation_snippets timestamps

The create-table migration declared created_at/updated_at NOT NULL without
the TimestampMixin's server_default=now(), so every insert failed with a
NotNullViolation in production (tests create tables from the models and
never saw it).

Revision ID: 20260707_223000
Revises: 20260707_213000
Create Date: 2026-07-07 22:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260707_223000"
down_revision: Union[str, tuple[str, str], None] = "20260707_213000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "dictation_snippets",
        "created_at",
        server_default=sa.func.now(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "dictation_snippets",
        "updated_at",
        server_default=sa.func.now(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "dictation_snippets",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "dictation_snippets",
        "updated_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
