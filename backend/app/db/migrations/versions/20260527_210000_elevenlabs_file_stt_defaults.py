"""move file STT defaults back to ElevenLabs Scribe v2

Revision ID: 20260527_210000
Revises: 20260527_200000
Create Date: 2026-05-27 21:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_210000"
down_revision: Union[str, None] = "20260527_200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDER = "elevenlabs"
MODEL = "scribe_v2"
LEGACY_PROVIDER = "openai"
LEGACY_MODEL = "gpt-4o-transcribe-diarize"


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
