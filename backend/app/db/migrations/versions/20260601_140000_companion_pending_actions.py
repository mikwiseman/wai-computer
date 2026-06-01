"""companion_pending_actions (propose→commit approval gate + offline queue)

Revision ID: 20260601_140000
Revises: 20260601_130000
Create Date: 2026-06-01 14:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260601_140000"
down_revision: Union[str, None] = "20260601_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companion_pending_actions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "conversation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("action_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hmac", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_target", sa.String(length=120), nullable=True),
        sa.Column("recipient_display", sa.String(length=200), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("receipt", postgresql.JSONB(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_companion_pending_actions_idempotency"
        ),
    )
    op.create_index(
        "ix_companion_pending_actions_user_id",
        "companion_pending_actions", ["user_id"],
    )
    op.create_index(
        "ix_companion_pending_actions_conversation_id",
        "companion_pending_actions", ["conversation_id"],
    )
    op.create_index(
        "ix_companion_pending_actions_status_expires",
        "companion_pending_actions", ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_companion_pending_actions_status_expires",
        table_name="companion_pending_actions",
    )
    op.drop_index(
        "ix_companion_pending_actions_conversation_id",
        table_name="companion_pending_actions",
    )
    op.drop_index(
        "ix_companion_pending_actions_user_id",
        table_name="companion_pending_actions",
    )
    op.drop_table("companion_pending_actions")
