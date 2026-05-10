"""enforce stable transcription model set

Revision ID: 20260510_130000
Revises: 20260508_150000
Create Date: 2026-05-10 13:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260510_130000"
down_revision: Union[str, None] = "20260508_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STABLE_DICTATION_PROVIDER = "elevenlabs"
STABLE_DICTATION_MODEL = "scribe_v2_realtime"
STABLE_RECORDING_PROVIDER = "elevenlabs"
STABLE_RECORDING_MODEL = "scribe_v2_realtime"
STABLE_FILE_PROVIDER = "elevenlabs"
STABLE_FILE_MODEL = "scribe_v2"
STABLE_POST_FILTER_PROVIDER = "anthropic"
STABLE_POST_FILTER_MODEL = "claude-haiku-4-5-20251001"

PREVIOUS_DICTATION_PROVIDER = "openai"
PREVIOUS_DICTATION_MODEL = "gpt-realtime-whisper"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users "
            "SET dictation_live_stt_provider = :dictation_provider, "
            "dictation_live_stt_model = :dictation_model, "
            "recording_live_stt_provider = :recording_provider, "
            "recording_live_stt_model = :recording_model, "
            "file_stt_provider = :file_provider, "
            "file_stt_model = :file_model, "
            "dictation_post_filter_enabled = true, "
            "dictation_post_filter_provider = :post_filter_provider, "
            "dictation_post_filter_model = :post_filter_model"
        ).bindparams(
            dictation_provider=STABLE_DICTATION_PROVIDER,
            dictation_model=STABLE_DICTATION_MODEL,
            recording_provider=STABLE_RECORDING_PROVIDER,
            recording_model=STABLE_RECORDING_MODEL,
            file_provider=STABLE_FILE_PROVIDER,
            file_model=STABLE_FILE_MODEL,
            post_filter_provider=STABLE_POST_FILTER_PROVIDER,
            post_filter_model=STABLE_POST_FILTER_MODEL,
        )
    )
    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        server_default=STABLE_DICTATION_PROVIDER,
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        server_default=STABLE_DICTATION_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_provider",
        server_default=STABLE_RECORDING_PROVIDER,
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_model",
        server_default=STABLE_RECORDING_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_provider",
        server_default=STABLE_FILE_PROVIDER,
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_model",
        server_default=STABLE_FILE_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        server_default="true",
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        server_default=STABLE_POST_FILTER_PROVIDER,
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=STABLE_POST_FILTER_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        server_default=PREVIOUS_DICTATION_PROVIDER,
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        server_default=PREVIOUS_DICTATION_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )
