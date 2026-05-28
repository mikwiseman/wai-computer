"""public voiceprint directory

Revision ID: 20260528_160000
Revises: 20260528_140000
Create Date: 2026-05-28 16:00:00.000000+00:00

Introduces a global opt-in voice directory so that one user's voiceprint can
be matched in another user's recordings. Two pieces:

1. ``people.directory_user_id`` flags Person rows that were auto-created from
   a directory match. The receiver's address book never gains entries from
   strangers unless we matched their voice in their own recording.
2. ``public_voiceprints`` (one row per opted-in user) stores a denormalised
   embedding + first/last name so cross-user matching is a single pgvector
   query that does not need to join through voiceprints + users + people.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260528_160000"
down_revision: Union[str, None] = "20260528_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "people",
        sa.Column(
            "directory_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_people_directory_user_id",
        "people",
        ["directory_user_id"],
    )

    op.create_table(
        "public_voiceprints",
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
            unique=True,
        ),
        sa.Column(
            "voiceprint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voiceprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float), nullable=False),
        sa.Column("embedding_model", sa.String(length=50), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Swap the column to pgvector and add the cosine IVFFlat index. We use
    # raw SQL so the migration does not require the pgvector ORM import.
    op.execute(
        "ALTER TABLE public_voiceprints ALTER COLUMN embedding TYPE vector(192) "
        "USING embedding::vector(192)"
    )
    op.execute(
        "CREATE INDEX ix_public_voiceprints_embedding "
        "ON public_voiceprints USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_public_voiceprints_embedding")
    op.drop_table("public_voiceprints")
    op.drop_index("ix_people_directory_user_id", table_name="people")
    op.drop_column("people", "directory_user_id")
