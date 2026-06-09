"""Add entity_facts (bi-temporal asserted facts)

The fact layer (P2): a (subject) predicate (object) triple with a validity window.
CURRENT iff invalid_at IS NULL; supersession closes the window (sets invalid_at +
superseded_by_id) and never deletes, so "what's true now" is a query and history
is preserved. created_at = ingest/transaction time; valid_at/invalid_at = world
time.

Revision ID: 20260610_130000
Revises: 20260610_120000
Create Date: 2026-06-10 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260610_130000"
down_revision: Union[str, tuple[str, str], None] = "20260610_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_facts",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "subject_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("predicate", sa.String(length=100), nullable=False),
        sa.Column("object_text", sa.Text(), nullable=False),
        sa.Column(
            "object_entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("source_kind", sa.String(length=20), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("importance", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "superseded_by_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entity_facts.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "user_id", "subject_entity_id", "predicate", "object_text",
            name="uq_entity_facts_triple",
        ),
    )
    op.create_index("ix_entity_facts_user_id", "entity_facts", ["user_id"])
    op.create_index(
        "ix_entity_facts_subject_entity_id", "entity_facts", ["subject_entity_id"]
    )
    op.create_index(
        "ix_entity_facts_current",
        "entity_facts",
        ["user_id", "subject_entity_id"],
        postgresql_where=sa.text("invalid_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entity_facts_current", table_name="entity_facts")
    op.drop_index("ix_entity_facts_subject_entity_id", table_name="entity_facts")
    op.drop_index("ix_entity_facts_user_id", table_name="entity_facts")
    op.drop_table("entity_facts")
