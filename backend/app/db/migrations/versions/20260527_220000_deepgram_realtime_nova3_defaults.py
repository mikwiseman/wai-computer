"""move realtime STT defaults to Deepgram Nova-3

Revision ID: 20260527_220000
Revises: 20260527_210000
Create Date: 2026-05-27 22:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_220000"
down_revision: Union[str, None] = "20260527_210000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDER = "deepgram"
MODEL = "nova-3"
LEGACY_PROVIDER = "openai"
LEGACY_MODEL = "gpt-realtime-whisper"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model,
                recording_live_stt_provider = :provider,
                recording_live_stt_model = :model
            """
        ).bindparams(provider=PROVIDER, model=MODEL)
    )
    for provider_column, model_column in (
        ("dictation_live_stt_provider", "dictation_live_stt_model"),
        ("recording_live_stt_provider", "recording_live_stt_model"),
    ):
        op.alter_column(
            "users",
            provider_column,
            existing_type=sa.String(length=40),
            server_default=PROVIDER,
            nullable=False,
        )
        op.alter_column(
            "users",
            model_column,
            existing_type=sa.String(length=100),
            server_default=MODEL,
            nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model,
                recording_live_stt_provider = :provider,
                recording_live_stt_model = :model
            """
        ).bindparams(provider=LEGACY_PROVIDER, model=LEGACY_MODEL)
    )
    for provider_column, model_column in (
        ("dictation_live_stt_provider", "dictation_live_stt_model"),
        ("recording_live_stt_provider", "recording_live_stt_model"),
    ):
        op.alter_column(
            "users",
            provider_column,
            existing_type=sa.String(length=40),
            server_default=LEGACY_PROVIDER,
            nullable=False,
        )
        op.alter_column(
            "users",
            model_column,
            existing_type=sa.String(length=100),
            server_default=LEGACY_MODEL,
            nullable=False,
        )
