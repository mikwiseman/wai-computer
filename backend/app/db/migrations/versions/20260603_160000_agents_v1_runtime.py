"""agent runtime v1 payload/cancel/action-origin fields

Revision ID: 20260603_160000
Revises: 20260603_151000
Create Date: 2026-06-03 09:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_160000"
down_revision: Union[str, None] = "20260603_151000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("trigger_payload", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companion_pending_actions",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "companion_pending_actions",
        sa.Column("agent_step_idx", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_companion_pending_actions_agent_run_id",
        "companion_pending_actions",
        ["agent_run_id"],
    )
    op.create_foreign_key(
        "fk_companion_pending_actions_agent_run_id_agent_runs",
        "companion_pending_actions",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_companion_pending_actions_agent_run_id_agent_runs",
        "companion_pending_actions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_companion_pending_actions_agent_run_id",
        table_name="companion_pending_actions",
    )
    op.drop_column("companion_pending_actions", "agent_step_idx")
    op.drop_column("companion_pending_actions", "agent_run_id")
    op.drop_column("agent_runs", "cancel_requested_at")
    op.drop_column("agent_runs", "trigger_payload")
