"""move dictation post-filter defaults to Cerebras gpt-oss

Revision ID: 20260604_160000
Revises: 20260604_150000
Create Date: 2026-06-04 16:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260604_160000"
down_revision = "20260604_150000"
branch_labels = None
depends_on = None

POST_FILTER_PROVIDER = "cerebras"
POST_FILTER_MODEL = "gpt-oss-120b"
PREVIOUS_PROVIDER = "openai"
PREVIOUS_MODEL = "gpt-5.5"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_provider = :provider,
                dictation_post_filter_model = :model
            """
        ).bindparams(provider=POST_FILTER_PROVIDER, model=POST_FILTER_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default=POST_FILTER_PROVIDER,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=POST_FILTER_MODEL,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_provider = :provider,
                dictation_post_filter_model = :model
            WHERE dictation_post_filter_provider = :current_provider
              AND dictation_post_filter_model = :current_model
            """
        ).bindparams(
            provider=PREVIOUS_PROVIDER,
            model=PREVIOUS_MODEL,
            current_provider=POST_FILTER_PROVIDER,
            current_model=POST_FILTER_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default=PREVIOUS_PROVIDER,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=PREVIOUS_MODEL,
    )
