"""entity_mentions (polymorphic source->entity provenance) + entities dedup key

Phase 2 of the Materials+Brain upgrade — populate the knowledge graph. Adds:

- ``entity_mentions``: a polymorphic edge linking an Entity to the source
  (``recording`` OR ``item``) that mentions it — the join that lets PDFs /
  videos / articles become first-class graph citizens alongside recordings.
- a unique constraint on ``entities(user_id, type, name)`` so the upsert path
  dedups exactly (fuzzy duplicates go to Review, never a silent merge).

Revision ID: 20260602_100000
Revises: 20260601_140000
Create Date: 2026-06-02 10:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260602_100000"
down_revision: Union[str, None] = "20260601_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_mentions",
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
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), server_default="1.0", nullable=False),
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
            "entity_id",
            "source_kind",
            "source_id",
            name="uq_entity_mentions_entity_source",
        ),
    )
    op.create_index("ix_entity_mentions_user_id", "entity_mentions", ["user_id"])
    op.create_index("ix_entity_mentions_entity", "entity_mentions", ["entity_id"])
    op.create_index(
        "ix_entity_mentions_user_source",
        "entity_mentions",
        ["user_id", "source_kind", "source_id"],
    )
    op.create_unique_constraint(
        "uq_entities_user_type_name", "entities", ["user_id", "type", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_entities_user_type_name", "entities", type_="unique")
    op.drop_index("ix_entity_mentions_user_source", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_entity", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_user_id", table_name="entity_mentions")
    op.drop_table("entity_mentions")
