"""items and item_chunks (universal second-brain content)

Creates the canonical ``items`` table (any non-recording content: articles,
PDFs, forwarded links, pasted notes, emails, MCP-ingested rows) and
``item_chunks`` (embedded text chunks, mirroring ``segments``). ANN (HNSW)
indexes on the embedding columns are added in a follow-up migration once the
tables carry data — at current per-user scale, user-filtered exact cosine is
fine and avoids an empty-index build.

Revision ID: 20260601_090000
Revises: 20260531_120000
Create Date: 2026-06-01 09:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260601_090000"
down_revision: Union[str, None] = "20260531_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_ref", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False, server_default="note"),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        sa.Column(
            "privacy_level",
            sa.String(length=20),
            nullable=False,
            server_default="internal",
        ),
        sa.Column(
            "authority_score", sa.Float(), nullable=False, server_default="0.5"
        ),
        sa.Column("salience_score", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="raw"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "content_hash", name="uq_items_user_content_hash"
        ),
    )
    op.create_index("ix_items_user_id", "items", ["user_id"])
    op.create_index("ix_items_user_created", "items", ["user_id", "created_at"])
    op.create_index("ix_items_user_occurred", "items", ["user_id", "occurred_at"])
    op.create_index("ix_items_user_source", "items", ["user_id", "source"])
    op.create_index("ix_items_user_kind", "items", ["user_id", "kind"])
    op.create_index("ix_items_user_state", "items", ["user_id", "state"])
    op.create_index("ix_items_simhash", "items", ["simhash"])
    op.create_index("ix_items_folder_id", "items", ["folder_id"])

    op.create_table(
        "item_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.UniqueConstraint("item_id", "seq", name="uq_item_chunks_item_seq"),
    )
    op.create_index("ix_item_chunks_item_id", "item_chunks", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_chunks_item_id", table_name="item_chunks")
    op.drop_table("item_chunks")
    for idx in (
        "ix_items_folder_id",
        "ix_items_simhash",
        "ix_items_user_state",
        "ix_items_user_kind",
        "ix_items_user_source",
        "ix_items_user_occurred",
        "ix_items_user_created",
        "ix_items_user_id",
    ):
        op.drop_index(idx, table_name="items")
    op.drop_table("items")
