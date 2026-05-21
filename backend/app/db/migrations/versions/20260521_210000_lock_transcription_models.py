"""lock user transcription models to the release defaults

Revision ID: 20260521_210000
Revises: 20260521_090000
Create Date: 2026-05-21 21:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_210000"
down_revision: Union[str, None] = "20260521_090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DICTATION_PROVIDER = "inworld"
DICTATION_MODEL = "inworld/inworld-stt-1"
RECORDING_PROVIDER = "inworld"
RECORDING_MODEL = "inworld/inworld-stt-1"
FILE_PROVIDER = "elevenlabs"
FILE_MODEL = "scribe_v2"
POST_FILTER_PROVIDER = "openai"
POST_FILTER_MODEL = "gpt-5.5"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :dictation_provider,
                dictation_live_stt_model = :dictation_model,
                recording_live_stt_provider = :recording_provider,
                recording_live_stt_model = :recording_model,
                file_stt_provider = :file_provider,
                file_stt_model = :file_model,
                dictation_post_filter_provider = :post_filter_provider,
                dictation_post_filter_model = :post_filter_model
            """
        ).bindparams(
            dictation_provider=DICTATION_PROVIDER,
            dictation_model=DICTATION_MODEL,
            recording_provider=RECORDING_PROVIDER,
            recording_model=RECORDING_MODEL,
            file_provider=FILE_PROVIDER,
            file_model=FILE_MODEL,
            post_filter_provider=POST_FILTER_PROVIDER,
            post_filter_model=POST_FILTER_MODEL,
        )
    )

    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=DICTATION_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=DICTATION_MODEL,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=RECORDING_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=RECORDING_MODEL,
        nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_provider",
        existing_type=sa.String(length=40),
        server_default=FILE_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "file_stt_model",
        existing_type=sa.String(length=100),
        server_default=FILE_MODEL,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_provider",
        existing_type=sa.String(length=40),
        server_default=POST_FILTER_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        existing_type=sa.String(length=100),
        server_default=POST_FILTER_MODEL,
        nullable=False,
    )


def downgrade() -> None:
    pass
