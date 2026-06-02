"""agents / agent_runs / agent_steps — durable working-agents journal (P6)

Re-creates the agents substrate (dropped in 20260407_120000) as a durable,
replayable Postgres journal on the existing Celery worker. Stable
``trigger_key`` (UNIQUE on agent_runs) makes a redelivered wake resume rather
than fork; ``UNIQUE(run_id, idx)`` orders the append-only step journal.

Revision ID: 20260602_120000
Revises: 20260601_141000
Create Date: 2026-06-02 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260602_120000"
down_revision: Union[str, None] = "20260601_141000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "autonomy", sa.String(length=20), nullable=False,
            server_default="propose",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true"),
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_agents_user_id", "agents", ["user_id"])
    op.create_index(
        "ix_agents_due", "agents", ["trigger_type", "enabled", "next_run_at"]
    )

    op.create_table(
        "agent_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "agent_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("trigger_key", sa.String(length=200), nullable=False),
        sa.Column("trigger_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default="pending",
        ),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("done_spec", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "next_step_idx", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint("trigger_key", name="uq_agent_runs_trigger_key"),
    )
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "agent_steps",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint("run_id", "idx", name="uq_agent_steps_run_idx"),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_steps_run_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agents_due", table_name="agents")
    op.drop_index("ix_agents_user_id", table_name="agents")
    op.drop_table("agents")
