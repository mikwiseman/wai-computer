"""remove OpenAI realtime STT preferences from user-selectable model set

Revision ID: 20260520_130000
Revises: 20260520_120000
Create Date: 2026-05-20 13:00:00.000000+00:00

OpenAI remains available for dictation cleanup, but no OpenAI realtime STT
model is part of the curated selectable STT set. Reset users pinned to the
old experimental realtime OpenAI entry back to the safe ElevenLabs default.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_130000"
down_revision: Union[str, None] = "20260520_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_REALTIME_PROVIDER = "elevenlabs"
DEFAULT_REALTIME_MODEL = "scribe_v2_realtime"


def upgrade() -> None:
    for provider_column, model_column in (
        ("dictation_live_stt_provider", "dictation_live_stt_model"),
        ("recording_live_stt_provider", "recording_live_stt_model"),
    ):
        op.execute(
            sa.text(
                f"""
                UPDATE users
                SET {provider_column} = :provider,
                    {model_column} = :model
                WHERE {provider_column} = 'openai'
                   OR {model_column} = 'gpt-realtime-whisper'
                """
            ).bindparams(provider=DEFAULT_REALTIME_PROVIDER, model=DEFAULT_REALTIME_MODEL)
        )


def downgrade() -> None:
    pass
