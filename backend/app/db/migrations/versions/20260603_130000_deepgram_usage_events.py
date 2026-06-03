"""add deepgram usage events

Revision ID: 20260603_130000
Revises: 20260603_120000
Create Date: 2026-06-03 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_130000"
down_revision: Union[str, None] = "20260603_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deepgram_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recording_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), server_default="deepgram", nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("audio_seconds", sa.Float(), nullable=True),
        sa.Column("billable_seconds", sa.Float(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_status_code", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=128), nullable=True),
        sa.Column("guard_code", sa.String(length=128), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deepgram_usage_events_created_at",
        "deepgram_usage_events",
        ["created_at"],
    )
    op.create_index(
        "ix_deepgram_usage_events_operation_status_created",
        "deepgram_usage_events",
        ["operation", "status", "created_at"],
    )
    op.create_index(
        "ix_deepgram_usage_events_recording_created",
        "deepgram_usage_events",
        ["recording_id", "created_at"],
    )
    op.create_index(
        "ix_deepgram_usage_events_recording_id",
        "deepgram_usage_events",
        ["recording_id"],
    )
    op.create_index(
        "ix_deepgram_usage_events_user_created",
        "deepgram_usage_events",
        ["user_id", "created_at"],
    )
    op.create_index("ix_deepgram_usage_events_user_id", "deepgram_usage_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_deepgram_usage_events_user_id", table_name="deepgram_usage_events")
    op.drop_index("ix_deepgram_usage_events_user_created", table_name="deepgram_usage_events")
    op.drop_index("ix_deepgram_usage_events_recording_id", table_name="deepgram_usage_events")
    op.drop_index(
        "ix_deepgram_usage_events_recording_created",
        table_name="deepgram_usage_events",
    )
    op.drop_index(
        "ix_deepgram_usage_events_operation_status_created",
        table_name="deepgram_usage_events",
    )
    op.drop_index("ix_deepgram_usage_events_created_at", table_name="deepgram_usage_events")
    op.drop_table("deepgram_usage_events")
