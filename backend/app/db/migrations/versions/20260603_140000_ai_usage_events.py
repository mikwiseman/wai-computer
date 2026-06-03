"""add unified ai usage events

Revision ID: 20260603_140000
Revises: 20260603_130000
Create Date: 2026-06-03 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_140000"
down_revision: Union[str, None] = "20260603_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recording_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("audio_seconds", sa.Float(), nullable=True),
        sa.Column("billable_seconds", sa.Float(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "pricing_status",
            sa.String(length=32),
            server_default="unpriced",
            nullable=False,
        ),
        sa.Column("provider_status_code", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=128), nullable=True),
        sa.Column("guard_code", sa.String(length=128), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"])
    op.create_index(
        "ix_ai_usage_events_conversation_id",
        "ai_usage_events",
        ["conversation_id"],
    )
    op.create_index("ix_ai_usage_events_feature_created", "ai_usage_events", ["feature", "created_at"])
    op.create_index("ix_ai_usage_events_item_id", "ai_usage_events", ["item_id"])
    op.create_index("ix_ai_usage_events_message_id", "ai_usage_events", ["message_id"])
    op.create_index("ix_ai_usage_events_model_created", "ai_usage_events", ["model", "created_at"])
    op.create_index(
        "ix_ai_usage_events_provider_created",
        "ai_usage_events",
        ["provider", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_provider_feature_status_created",
        "ai_usage_events",
        ["provider", "feature", "status", "created_at"],
    )
    op.create_index("ix_ai_usage_events_recording_id", "ai_usage_events", ["recording_id"])
    op.create_index(
        "ix_ai_usage_events_status_created",
        "ai_usage_events",
        ["status", "created_at"],
    )
    op.create_index("ix_ai_usage_events_user_created", "ai_usage_events", ["user_id", "created_at"])
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO ai_usage_events (
                created_at,
                user_id,
                recording_id,
                provider,
                feature,
                operation,
                status,
                model,
                audio_seconds,
                billable_seconds,
                channel_count,
                audio_bytes,
                latency_ms,
                pricing_status,
                provider_status_code,
                provider_error_code,
                guard_code,
                error_type,
                request_id,
                task_id,
                details
            )
            SELECT
                created_at,
                user_id,
                recording_id,
                provider,
                CASE
                    WHEN purpose IN ('recording', 'dictation', 'materials', 'telegram')
                    THEN purpose
                    ELSE 'transcription'
                END,
                operation,
                status,
                model,
                audio_seconds,
                billable_seconds,
                channel_count,
                audio_bytes,
                latency_ms,
                'unpriced',
                provider_status_code,
                provider_error_code,
                guard_code,
                error_type,
                request_id,
                task_id,
                jsonb_build_object('source', 'deepgram_usage_events', 'purpose', purpose)
            FROM deepgram_usage_events
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_status_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_recording_id", table_name="ai_usage_events")
    op.drop_index(
        "ix_ai_usage_events_provider_feature_status_created",
        table_name="ai_usage_events",
    )
    op.drop_index("ix_ai_usage_events_provider_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_model_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_message_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_item_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_feature_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_conversation_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_created_at", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
