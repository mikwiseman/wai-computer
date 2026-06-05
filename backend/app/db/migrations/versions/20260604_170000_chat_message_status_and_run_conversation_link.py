"""chat message streaming status + agent run conversation link

Adds:
* ``chat_messages.status`` (streaming | complete | failed) so an assistant
  message can be created at turn start and finalized when the stream ends —
  a dropped SSE stream no longer loses the turn. Existing rows backfill to
  ``complete``.
* ``agent_runs.origin_message_id`` so a chat can hand a job to a durable
  background run that reports its result back into the same conversation
  thread. ``agent_runs.conversation_id`` is owned by revision
  ``20260605_090000``.

Revision ID: 20260604_170000
Revises: 20260604_150000
Create Date: 2026-06-04 17:00:00.000000

NOTE: the (currently uncommitted) cerebras migration ``20260604_160000`` also
descends from ``20260604_150000``; when both land a one-line alembic merge
migration reconciles the two heads.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260604_170000"
down_revision = "20260604_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="complete",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("origin_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_origin_message_id_chat_messages",
        "agent_runs",
        "chat_messages",
        ["origin_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_runs_origin_message_id_chat_messages",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "origin_message_id")
    op.drop_column("chat_messages", "status")
