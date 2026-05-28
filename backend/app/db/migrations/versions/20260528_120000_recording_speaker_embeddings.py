"""retain recording speaker embeddings for rematch and speaker learning

Revision ID: 20260528_120000
Revises: 20260527_220000
Create Date: 2026-05-28 12:00:00.000000+00:00
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260528_120000"
down_revision: Union[str, None] = "20260527_220000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voiceprints",
        sa.Column("source_raw_label", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_voiceprints_source_recording_raw_label",
        "voiceprints",
        ["source_recording_id", "source_raw_label"],
    )

    op.create_table(
        "recording_speaker_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recording_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_label", sa.String(100), nullable=False),
        sa.Column("embedding", Vector(192), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recording_speaker_embeddings_user_id",
        "recording_speaker_embeddings",
        ["user_id"],
    )
    op.create_index(
        "ix_recording_speaker_embeddings_recording_id",
        "recording_speaker_embeddings",
        ["recording_id"],
    )
    op.create_index(
        "uq_recording_speaker_embeddings_recording_raw_model",
        "recording_speaker_embeddings",
        ["recording_id", "raw_label", "model"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_recording_speaker_embeddings_recording_raw_model",
        table_name="recording_speaker_embeddings",
    )
    op.drop_index(
        "ix_recording_speaker_embeddings_recording_id",
        table_name="recording_speaker_embeddings",
    )
    op.drop_index(
        "ix_recording_speaker_embeddings_user_id",
        table_name="recording_speaker_embeddings",
    )
    op.drop_table("recording_speaker_embeddings")

    op.drop_index("ix_voiceprints_source_recording_raw_label", table_name="voiceprints")
    op.drop_column("voiceprints", "source_raw_label")
