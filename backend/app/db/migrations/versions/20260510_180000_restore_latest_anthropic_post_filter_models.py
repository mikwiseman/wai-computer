"""restore latest anthropic post-filter model ids

Revision ID: 20260510_180000
Revises: 20260510_170000
Create Date: 2026-05-10 18:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260510_180000"
down_revision: Union[str, None] = "20260510_170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"
OPUS_MODEL = "claude-opus-4-7"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users "
            "SET dictation_post_filter_model = CASE "
            "WHEN dictation_post_filter_model IN ("
            "'claude-3-5-haiku-20241022', "
            "'claude-haiku-4-5-20251001'"
            ") "
            "THEN :haiku_model "
            "WHEN dictation_post_filter_model = 'claude-sonnet-4-20250514' "
            "THEN :sonnet_model "
            "WHEN dictation_post_filter_model = 'claude-opus-4-1-20250805' "
            "THEN :opus_model "
            "ELSE dictation_post_filter_model "
            "END "
            "WHERE dictation_post_filter_model IN ("
            "'claude-3-5-haiku-20241022', "
            "'claude-haiku-4-5-20251001', "
            "'claude-sonnet-4-20250514', "
            "'claude-opus-4-1-20250805'"
            ")"
        ).bindparams(
            haiku_model=HAIKU_MODEL,
            sonnet_model=SONNET_MODEL,
            opus_model=OPUS_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=HAIKU_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users "
            "SET dictation_post_filter_model = CASE "
            "WHEN dictation_post_filter_model = :haiku_model "
            "THEN 'claude-3-5-haiku-20241022' "
            "WHEN dictation_post_filter_model = :sonnet_model "
            "THEN 'claude-sonnet-4-20250514' "
            "WHEN dictation_post_filter_model = :opus_model "
            "THEN 'claude-opus-4-1-20250805' "
            "ELSE dictation_post_filter_model "
            "END "
            "WHERE dictation_post_filter_model IN (:haiku_model, :sonnet_model, :opus_model)"
        ).bindparams(
            haiku_model=HAIKU_MODEL,
            sonnet_model=SONNET_MODEL,
            opus_model=OPUS_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default="claude-3-5-haiku-20241022",
        existing_type=sa.String(100),
        existing_nullable=False,
    )
