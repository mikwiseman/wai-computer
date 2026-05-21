"""make Inworld the default realtime STT model

Revision ID: 20260521_090000
Revises: 20260520_220000
Create Date: 2026-05-21 09:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_090000"
down_revision: Union[str, None] = "20260520_220000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_PROVIDER = "soniox"
OLD_MODEL = "stt-rt-v4"
NEW_PROVIDER = "inworld"
NEW_MODEL = "inworld/inworld-stt-1"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_live_stt_provider = :new_provider,
                dictation_live_stt_model = :new_model
            WHERE dictation_live_stt_provider = :old_provider
              AND dictation_live_stt_model = :old_model
            """
        ).bindparams(
            new_provider=NEW_PROVIDER,
            new_model=NEW_MODEL,
            old_provider=OLD_PROVIDER,
            old_model=OLD_MODEL,
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET recording_live_stt_provider = :new_provider,
                recording_live_stt_model = :new_model
            WHERE recording_live_stt_provider = :old_provider
              AND recording_live_stt_model = :old_model
            """
        ).bindparams(
            new_provider=NEW_PROVIDER,
            new_model=NEW_MODEL,
            old_provider=OLD_PROVIDER,
            old_model=OLD_MODEL,
        )
    )

    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=NEW_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=NEW_MODEL,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=NEW_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=NEW_MODEL,
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "dictation_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=OLD_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=OLD_MODEL,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_provider",
        existing_type=sa.String(length=40),
        server_default=OLD_PROVIDER,
        nullable=False,
    )
    op.alter_column(
        "users",
        "recording_live_stt_model",
        existing_type=sa.String(length=100),
        server_default=OLD_MODEL,
        nullable=False,
    )
