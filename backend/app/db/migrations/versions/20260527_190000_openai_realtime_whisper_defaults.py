"""move realtime STT defaults to OpenAI GPT Realtime Whisper

Revision ID: 20260527_190000
Revises: 20260527_180000
Create Date: 2026-05-27 19:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_190000"
down_revision: Union[str, None] = "20260527_180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDER = "openai"
MODEL = "gpt-realtime-whisper"


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
    legacy_provider = "inworld"
    legacy_model = "inworld/inworld-stt-1"
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model,
                recording_live_stt_provider = :provider,
                recording_live_stt_model = :model
            """
        ).bindparams(provider=legacy_provider, model=legacy_model)
    )
    for provider_column, model_column in (
        ("dictation_live_stt_provider", "dictation_live_stt_model"),
        ("recording_live_stt_provider", "recording_live_stt_model"),
    ):
        op.alter_column(
            "users",
            provider_column,
            existing_type=sa.String(length=40),
            server_default=legacy_provider,
            nullable=False,
        )
        op.alter_column(
            "users",
            model_column,
            existing_type=sa.String(length=100),
            server_default=legacy_model,
            nullable=False,
        )
