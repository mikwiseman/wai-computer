"""brain spaces canonical markdown pages

Revision ID: 20260604_121000
Revises: 20260603_170000
Create Date: 2026-06-04 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260604_121000"
down_revision: Union[str, None] = "20260603_170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brain_spaces",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("kind", sa.String(length=40), server_default="personal", nullable=False),
        sa.Column("engine_profile", sa.String(length=40), server_default="waibrain", nullable=False),
        sa.Column("visibility", sa.String(length=40), server_default="private", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "slug", name="uq_brain_spaces_owner_slug"),
    )
    op.create_index("ix_brain_spaces_owner", "brain_spaces", ["owner_user_id"])

    op.create_table(
        "brain_space_members",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="viewer", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "user_id", name="uq_brain_space_members_space_user"),
    )
    op.create_index("ix_brain_space_members_user", "brain_space_members", ["user_id"])
    op.create_index(
        "ix_brain_space_members_space_role", "brain_space_members", ["space_id", "role"]
    )

    op.create_table(
        "brain_space_sources",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id",
            "source_kind",
            "source_id",
            name="uq_brain_space_sources_space_source",
        ),
    )
    op.create_index("ix_brain_space_sources_space", "brain_space_sources", ["space_id"])
    op.create_index(
        "ix_brain_space_sources_source", "brain_space_sources", ["source_kind", "source_id"]
    )

    op.create_table(
        "brain_pages",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("slug", sa.String(length=320), nullable=False),
        sa.Column("kind", sa.String(length=40), server_default="note", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("frontmatter", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "slug", name="uq_brain_pages_space_slug"),
    )
    op.create_index("ix_brain_pages_space_kind", "brain_pages", ["space_id", "kind"])
    op.create_index("ix_brain_pages_space_status", "brain_pages", ["space_id", "status"])

    op.create_table(
        "brain_claims",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("authority", sa.String(length=40), server_default="self", nullable=False),
        sa.Column("salience", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["page_id"], ["brain_pages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_by_claim_id"], ["brain_claims.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "dedup_key", name="uq_brain_claims_space_dedup"),
    )
    op.create_index("ix_brain_claims_page", "brain_claims", ["page_id"])
    op.create_index(
        "ix_brain_claims_space_kind_status",
        "brain_claims",
        ["space_id", "kind", "status"],
    )

    op.create_table(
        "brain_review_packs",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), server_default="bridge", nullable=False),
        sa.Column("risk", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("proposals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["space_id"], ["brain_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_brain_review_packs_space_created", "brain_review_packs", ["space_id", "created_at"]
    )
    op.create_index(
        "ix_brain_review_packs_space_status", "brain_review_packs", ["space_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_brain_review_packs_space_status", table_name="brain_review_packs")
    op.drop_index("ix_brain_review_packs_space_created", table_name="brain_review_packs")
    op.drop_table("brain_review_packs")

    op.drop_index("ix_brain_claims_space_kind_status", table_name="brain_claims")
    op.drop_index("ix_brain_claims_page", table_name="brain_claims")
    op.drop_table("brain_claims")

    op.drop_index("ix_brain_pages_space_status", table_name="brain_pages")
    op.drop_index("ix_brain_pages_space_kind", table_name="brain_pages")
    op.drop_table("brain_pages")

    op.drop_index("ix_brain_space_sources_source", table_name="brain_space_sources")
    op.drop_index("ix_brain_space_sources_space", table_name="brain_space_sources")
    op.drop_table("brain_space_sources")

    op.drop_index("ix_brain_space_members_space_role", table_name="brain_space_members")
    op.drop_index("ix_brain_space_members_user", table_name="brain_space_members")
    op.drop_table("brain_space_members")

    op.drop_index("ix_brain_spaces_owner", table_name="brain_spaces")
    op.drop_table("brain_spaces")
