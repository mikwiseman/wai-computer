"""conversation_chunks (Wai chats become first-class Brain sources)

A Wai chat is a real Brain source like a recording or a material, but until now
nothing made it searchable or linkable: ``unified_search`` only unioned
``segments`` (recordings) and ``item_chunks`` (items), and the entity-mention
pipeline never ran on chat content. So chats could be *counted* as "needs
linking" yet could never actually be linked — pressing the button did nothing.

This adds ``conversation_chunks`` (embedded text chunks of a conversation,
mirroring ``item_chunks`` for items) so chats join unified search + Ask, plus a
``brain_linked_message_count`` watermark on ``conversations`` that debounces the
auto-link-on-turn-completion job (re-extract only when new messages arrived).

The GIN FTS index expression matches ``unified_search`` EXACTLY (same 'russian'
config + ``lower(content COLLATE "und-x-icu")``) or the planner won't use it.

Revision ID: 20260607_120000
Revises: 20260605_110000
Create Date: 2026-06-07 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260607_120000"
down_revision: Union[str, None] = "20260605_110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.UniqueConstraint(
            "conversation_id", "seq", name="uq_conversation_chunks_conversation_seq"
        ),
    )
    op.create_index(
        "ix_conversation_chunks_conversation_id",
        "conversation_chunks",
        ["conversation_id"],
    )
    # Must match the query expression in unified_search.py EXACTLY (same
    # 'russian' config + lower(... COLLATE "und-x-icu")) or the planner won't
    # use the index — identical to idx_item_chunks_content_fts.
    op.execute(
        """CREATE INDEX IF NOT EXISTS idx_conversation_chunks_content_fts ON conversation_chunks """
        """USING gin (to_tsvector('russian', lower(content COLLATE "und-x-icu")))"""
    )

    op.add_column(
        "conversations",
        sa.Column(
            "brain_linked_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "brain_linked_message_count")
    op.execute("DROP INDEX IF EXISTS idx_conversation_chunks_content_fts")
    op.drop_index(
        "ix_conversation_chunks_conversation_id", table_name="conversation_chunks"
    )
    op.drop_table("conversation_chunks")
