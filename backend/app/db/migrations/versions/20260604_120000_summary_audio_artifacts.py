"""add summary audio artifacts

Revision ID: 20260604_120000
Revises: 20260603_151000
Create Date: 2026-06-04 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260604_120000"
down_revision: Union[str, None] = "20260603_151000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "summary_audio_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
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
            nullable=True,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("summary_hash", sa.String(length=64), nullable=False),
        sa.Column("input_char_count", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("voice_id", sa.String(length=120), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("storage_path", sa.String(length=1000), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(recording_id IS NOT NULL AND item_id IS NULL AND source_kind = 'recording') OR "
            "(recording_id IS NULL AND item_id IS NOT NULL AND source_kind = 'item')",
            name="ck_summary_audio_exactly_one_source",
        ),
    )
    op.create_index(
        "ix_summary_audio_artifacts_user_id", "summary_audio_artifacts", ["user_id"]
    )
    op.create_index(
        "ix_summary_audio_artifacts_recording_id",
        "summary_audio_artifacts",
        ["recording_id"],
    )
    op.create_index(
        "ix_summary_audio_artifacts_item_id", "summary_audio_artifacts", ["item_id"]
    )
    op.create_index(
        "ix_summary_audio_artifacts_status", "summary_audio_artifacts", ["status"]
    )
    op.create_index(
        "ix_summary_audio_artifacts_user_requested",
        "summary_audio_artifacts",
        ["user_id", "requested_at"],
    )
    op.create_index(
        "ux_summary_audio_active_recording",
        "summary_audio_artifacts",
        ["recording_id"],
        unique=True,
        postgresql_where=sa.text("recording_id IS NOT NULL AND status IN ('queued', 'running')"),
    )
    op.create_index(
        "ux_summary_audio_active_item",
        "summary_audio_artifacts",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("item_id IS NOT NULL AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ux_summary_audio_active_item", table_name="summary_audio_artifacts")
    op.drop_index("ux_summary_audio_active_recording", table_name="summary_audio_artifacts")
    op.drop_index(
        "ix_summary_audio_artifacts_user_requested", table_name="summary_audio_artifacts"
    )
    op.drop_index("ix_summary_audio_artifacts_status", table_name="summary_audio_artifacts")
    op.drop_index("ix_summary_audio_artifacts_item_id", table_name="summary_audio_artifacts")
    op.drop_index(
        "ix_summary_audio_artifacts_recording_id", table_name="summary_audio_artifacts"
    )
    op.drop_index("ix_summary_audio_artifacts_user_id", table_name="summary_audio_artifacts")
    op.drop_table("summary_audio_artifacts")
