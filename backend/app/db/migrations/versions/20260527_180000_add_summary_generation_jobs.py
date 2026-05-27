"""add summary generation jobs

Revision ID: 20260527_180000
Revises: 20260527_150000
Create Date: 2026-05-27 18:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260527_180000"
down_revision: Union[str, None] = "20260527_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "summary_generation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recording_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("transcript_hash", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        op.f("ix_summary_generation_jobs_recording_id"),
        "summary_generation_jobs",
        ["recording_id"],
    )
    op.create_index(
        op.f("ix_summary_generation_jobs_user_id"),
        "summary_generation_jobs",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_summary_generation_jobs_status"),
        "summary_generation_jobs",
        ["status"],
    )
    op.create_index(
        "ux_summary_generation_jobs_active_recording",
        "summary_generation_jobs",
        ["recording_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_summary_generation_jobs_active_recording",
        table_name="summary_generation_jobs",
    )
    op.drop_index(op.f("ix_summary_generation_jobs_status"), table_name="summary_generation_jobs")
    op.drop_index(op.f("ix_summary_generation_jobs_user_id"), table_name="summary_generation_jobs")
    op.drop_index(op.f("ix_summary_generation_jobs_recording_id"), table_name="summary_generation_jobs")
    op.drop_table("summary_generation_jobs")
