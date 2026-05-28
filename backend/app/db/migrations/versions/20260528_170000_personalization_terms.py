"""personalization terminology and summary overrides

Revision ID: 20260528_170000
Revises: 20260528_160000
Create Date: 2026-05-28 17:00:00.000000+00:00
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260528_170000"
down_revision: Union[str, None] = "20260528_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "summary_generation_jobs",
        sa.Column("instructions_override", sa.Text(), nullable=True),
    )

    op.create_table(
        "personalization_import_jobs",
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
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_personalization_import_jobs_user_id",
        "personalization_import_jobs",
        ["user_id"],
    )
    op.create_index(
        "ix_personalization_import_jobs_status",
        "personalization_import_jobs",
        ["status"],
    )

    op.create_table(
        "personalization_terms",
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
            "import_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("personalization_import_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("term", sa.String(length=200), nullable=False),
        sa.Column("normalized_term", sa.String(length=200), nullable=False),
        sa.Column("replacement", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="1"),
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
            "user_id",
            "normalized_term",
            name="uq_personalization_terms_user_normalized_term",
        ),
    )
    op.create_index(
        "ix_personalization_terms_user_status",
        "personalization_terms",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_personalization_terms_import_job_id",
        "personalization_terms",
        ["import_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_personalization_terms_import_job_id", table_name="personalization_terms")
    op.drop_index("ix_personalization_terms_user_status", table_name="personalization_terms")
    op.drop_table("personalization_terms")
    op.drop_index(
        "ix_personalization_import_jobs_status",
        table_name="personalization_import_jobs",
    )
    op.drop_index(
        "ix_personalization_import_jobs_user_id",
        table_name="personalization_import_jobs",
    )
    op.drop_table("personalization_import_jobs")
    op.drop_column("summary_generation_jobs", "instructions_override")
