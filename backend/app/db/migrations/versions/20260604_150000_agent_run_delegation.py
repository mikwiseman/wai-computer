"""agent run parent child delegation

Revision ID: 20260604_150000
Revises: 20260604_140000
Create Date: 2026-06-04 15:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260604_150000"
down_revision = "20260604_140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("parent_step_idx", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_parent_run_id_agent_runs",
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_agent_runs_parent_run_id"),
        "agent_runs",
        ["parent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_user_parent",
        "agent_runs",
        ["user_id", "parent_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_user_parent", table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_parent_run_id"), table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_parent_run_id_agent_runs",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "parent_step_idx")
    op.drop_column("agent_runs", "parent_run_id")
