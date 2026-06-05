"""wai agent sessions and telegram context

Revision ID: 20260605_090000
Revises: 20260604_160000
Create Date: 2026-06-05 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260605_090000"
down_revision = "20260604_160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_conversation_id_conversations",
        "agent_runs",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_agent_runs_conversation_id"),
        "agent_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_user_conversation",
        "agent_runs",
        ["user_id", "conversation_id"],
        unique=False,
    )
    op.add_column(
        "telegram_accounts",
        sa.Column("active_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_accounts", "active_context")
    op.drop_index("ix_agent_runs_user_conversation", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_conversation_id"), table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_conversation_id_conversations",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "conversation_id")
