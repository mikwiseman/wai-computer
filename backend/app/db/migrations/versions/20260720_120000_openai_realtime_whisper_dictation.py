"""dictation live STT to OpenAI gpt-realtime-whisper; smart cleanup default

Dictation moves to OpenAI ``gpt-realtime-whisper`` through the realtime proxy
(recording stays on Deepgram Nova-3). Dictation cleanup returns as a default:
the June "disable cleanup" migration zeroed every user to ``none`` — that
state reflects the old Cerebras cleanup being retired, not a user choice — so
users sitting on ``none`` move to the new ``medium`` smart cleanup.

Revision ID: 20260720_120000
Revises: 20260719_120000
Create Date: 2026-07-20 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_120000"
down_revision: Union[str, None] = "20260719_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DICTATION_PROVIDER = "openai"
DICTATION_MODEL = "gpt-realtime-whisper"
LEGACY_DICTATION_PROVIDER = "deepgram"
LEGACY_DICTATION_MODEL = "nova-3"
CLEANUP_LEVEL = "medium"
LEGACY_CLEANUP_LEVEL = "none"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model
            """
        ).bindparams(provider=DICTATION_PROVIDER, model=DICTATION_MODEL)
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
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_cleanup_level = :level
            WHERE dictation_cleanup_level = :legacy_level
            """
        ).bindparams(level=CLEANUP_LEVEL, legacy_level=LEGACY_CLEANUP_LEVEL)
    )
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        existing_type=sa.String(length=20),
        server_default=CLEANUP_LEVEL,
        nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model
            """
        ).bindparams(provider=LEGACY_DICTATION_PROVIDER, model=LEGACY_DICTATION_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=LEGACY_DICTATION_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=LEGACY_DICTATION_MODEL,
        nullable=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_cleanup_level = :legacy_level
            WHERE dictation_cleanup_level = :level
            """
        ).bindparams(level=CLEANUP_LEVEL, legacy_level=LEGACY_CLEANUP_LEVEL)
    )
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        existing_type=sa.String(length=20),
        server_default=LEGACY_CLEANUP_LEVEL,
        nullable=False,
    )
