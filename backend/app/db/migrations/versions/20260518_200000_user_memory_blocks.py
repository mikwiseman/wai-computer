"""create user_memory_blocks and user_memory_log

Revision ID: 20260518_200000
Revises: 20260518_190000
Create Date: 2026-05-18 20:00:00.000000+00:00

Backs Wai's long-term memory layer (Letta core-block + gbrain compiled-truth
hybrid). Each user owns a small fixed set of labelled markdown blocks that
render into the cacheable system prefix; the agent edits them via the
`remember` tool and the nightly consolidator. user_memory_log is an
append-only audit trail so we can roll back bad writes.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260518_200000"
down_revision: Union[str, None] = "20260518_190000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memory_blocks",
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
            index=True,
        ),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("char_limit", sa.Integer, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(20), nullable=False),
        sa.UniqueConstraint("user_id", "label", name="uq_user_memory_blocks_user_label"),
    )

    op.create_table(
        "user_memory_log",
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
            index=True,
        ),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("before_body", sa.Text, nullable=False),
        sa.Column("after_body", sa.Text, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_memory_log")
    op.drop_table("user_memory_blocks")
