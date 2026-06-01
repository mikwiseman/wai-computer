"""move file STT defaults to Deepgram nova-3

Revision ID: 20260531_120000
Revises: 20260531_160000
Create Date: 2026-05-31 12:00:00.000000

Re-parented onto 20260531_160000 (russian_fts_config) to keep a single alembic
head after concurrent migrations landed on main; this migration is independent
(file STT defaults only) so ordering relative to them does not matter.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_120000"
down_revision: Union[str, None] = "20260531_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDER = "deepgram"
MODEL = "nova-3"
LEGACY_PROVIDER = "elevenlabs"
LEGACY_MODEL = "scribe_v2"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET file_stt_provider = :provider,
                file_stt_model = :model
            """
        ).bindparams(provider=PROVIDER, model=MODEL)
    )
    op.alter_column(
        "users",
        "file_stt_provider",
        existing_type=sa.String(length=40),
        server_default=PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_model",
        existing_type=sa.String(length=100),
        server_default=MODEL,
        nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET file_stt_provider = :provider,
                file_stt_model = :model
            """
        ).bindparams(provider=LEGACY_PROVIDER, model=LEGACY_MODEL)
    )
    op.alter_column(
        "users",
        "file_stt_provider",
        existing_type=sa.String(length=40),
        server_default=LEGACY_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_model",
        existing_type=sa.String(length=100),
        server_default=LEGACY_MODEL,
        nullable=False,
    )
