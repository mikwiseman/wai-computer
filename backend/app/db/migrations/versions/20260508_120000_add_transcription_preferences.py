"""add transcription preferences to users

Revision ID: 20260508_120000
Revises: 20260505_120000
Create Date: 2026-05-08 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260508_120000"
down_revision: Union[str, None] = "20260505_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("dictation_live_stt_provider", sa.String(40), server_default="openai", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "dictation_live_stt_model",
            sa.String(100),
            server_default="gpt-realtime-whisper",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "recording_live_stt_provider",
            sa.String(40),
            server_default="elevenlabs",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "recording_live_stt_model",
            sa.String(100),
            server_default="scribe_v2_realtime",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("file_stt_provider", sa.String(40), server_default="elevenlabs", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("file_stt_model", sa.String(100), server_default="scribe_v2", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("dictation_post_filter_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "dictation_post_filter_provider",
            sa.String(40),
            server_default="anthropic",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "dictation_post_filter_model",
            sa.String(100),
            server_default="claude-haiku-4-5",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "dictation_post_filter_model")
    op.drop_column("users", "dictation_post_filter_provider")
    op.drop_column("users", "dictation_post_filter_enabled")
    op.drop_column("users", "file_stt_model")
    op.drop_column("users", "file_stt_provider")
    op.drop_column("users", "recording_live_stt_model")
    op.drop_column("users", "recording_live_stt_provider")
    op.drop_column("users", "dictation_live_stt_model")
    op.drop_column("users", "dictation_live_stt_provider")
