"""flip dictation_post_filter from anthropic to openai

Revision ID: 20260518_150000
Revises: 20260518_140000
Create Date: 2026-05-18 15:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_150000"
down_revision: Union[str, None] = "20260518_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Flip any anthropic dictation post-filter setting to OpenAI gpt-5.5 —
    # the only supported provider+model after the May 2026 LLM swap.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_provider = 'openai',
                dictation_post_filter_model = 'gpt-5.5'
            WHERE dictation_post_filter_provider = 'anthropic'
            """
        )
    )
    # Update column server_defaults so newly-registered rows pick the new value.
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default="openai",
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default="gpt-5.5",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default="anthropic",
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default="claude-haiku-4-5",
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_provider = 'anthropic',
                dictation_post_filter_model = 'claude-haiku-4-5'
            WHERE dictation_post_filter_provider = 'openai'
            """
        )
    )
