"""fix anthropic post-filter model ids

Revision ID: 20260510_170000
Revises: 20260510_130000
Create Date: 2026-05-10 17:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260510_170000"
down_revision: Union[str, None] = "20260510_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_MODEL = "claude-3-5-haiku-20241022"
SONNET_MODEL = "claude-sonnet-4-20250514"
OPUS_MODEL = "claude-opus-4-1-20250805"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users "
            "SET dictation_post_filter_model = CASE "
            "WHEN dictation_post_filter_model IN "
            "('claude-haiku-4-5', 'claude-haiku-4-5-20251001') "
            "THEN :default_model "
            "WHEN dictation_post_filter_model = 'claude-sonnet-4-6' "
            "THEN :sonnet_model "
            "WHEN dictation_post_filter_model IN ('claude-opus-4-6', 'claude-opus-4-7') "
            "THEN :opus_model "
            "ELSE dictation_post_filter_model "
            "END"
        ).bindparams(
            default_model=DEFAULT_MODEL,
            sonnet_model=SONNET_MODEL,
            opus_model=OPUS_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=DEFAULT_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET dictation_post_filter_model = :old_model "
            "WHERE dictation_post_filter_model = :default_model"
        ).bindparams(old_model="claude-haiku-4-5-20251001", default_model=DEFAULT_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default="claude-haiku-4-5-20251001",
        existing_type=sa.String(100),
        existing_nullable=False,
    )
