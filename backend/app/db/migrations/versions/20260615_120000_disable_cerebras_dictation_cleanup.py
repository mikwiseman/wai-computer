"""disable Cerebras dictation cleanup defaults

Revision ID: 20260615_120000
Revises: 20260614_123000
Create Date: 2026-06-15 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_120000"
down_revision: Union[str, tuple[str, str], None] = "20260614_123000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DISABLED_PROVIDER = "disabled"
DISABLED_MODEL = "none"
PREVIOUS_PROVIDER = "cerebras"
PREVIOUS_MODEL = "gpt-oss-120b"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_enabled = false,
                dictation_cleanup_level = 'none',
                dictation_post_filter_provider = :provider,
                dictation_post_filter_model = :model
            """
        ).bindparams(provider=DISABLED_PROVIDER, model=DISABLED_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        server_default=sa.text("false"),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        server_default="none",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default=DISABLED_PROVIDER,
        existing_type=sa.String(length=40),
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=DISABLED_MODEL,
        existing_type=sa.String(length=100),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_enabled = true,
                dictation_cleanup_level = 'light',
                dictation_post_filter_provider = :provider,
                dictation_post_filter_model = :model
            WHERE dictation_post_filter_provider = :current_provider
              AND dictation_post_filter_model = :current_model
            """
        ).bindparams(
            provider=PREVIOUS_PROVIDER,
            model=PREVIOUS_MODEL,
            current_provider=DISABLED_PROVIDER,
            current_model=DISABLED_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        server_default=sa.text("true"),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        server_default="light",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default=PREVIOUS_PROVIDER,
        existing_type=sa.String(length=40),
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=PREVIOUS_MODEL,
        existing_type=sa.String(length=100),
    )
