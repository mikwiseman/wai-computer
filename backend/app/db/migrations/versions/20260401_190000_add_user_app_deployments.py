"""add user app deployments

Revision ID: 20260401_190000
Revises: 20260401_130000
Create Date: 2026-04-01 19:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260401_190000"
down_revision: Union[str, None] = "20260401_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_app_deployments",
        sa.Column("user_app_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_deployment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deployment_mode", sa.String(length=20), nullable=False),
        sa.Column("deployment_target", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("generated_slug", sa.String(length=120), nullable=False),
        sa.Column("bundle_cache_key", sa.String(length=180), nullable=False),
        sa.Column("cloudflare_project_name", sa.String(length=100), nullable=True),
        sa.Column("deployment_url", sa.String(length=500), nullable=True),
        sa.Column("alias_url", sa.String(length=500), nullable=True),
        sa.Column("live_url", sa.String(length=500), nullable=True),
        sa.Column("bundle_kind", sa.String(length=50), nullable=True),
        sa.Column("framework", sa.String(length=50), nullable=True),
        sa.Column("generation_provider", sa.String(length=50), nullable=True),
        sa.Column("build_output_dir", sa.String(length=120), nullable=True),
        sa.Column("build_command", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_deployment_id"], ["user_app_deployments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_app_id"], ["user_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_app_deployments_app_created",
        "user_app_deployments",
        ["user_app_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_app_deployments_user_app_id",
        "user_app_deployments",
        ["user_app_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_app_deployments_user_app_id", table_name="user_app_deployments")
    op.drop_index("ix_user_app_deployments_app_created", table_name="user_app_deployments")
    op.drop_table("user_app_deployments")
