"""drop user_apps, app_items, user_app_deployments tables

Revision ID: 20260406_120000
Revises: 20260403_120000
Create Date: 2026-04-06 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260406_120000"
down_revision: Union[str, None] = "20260403_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop in dependency order: deployments -> items -> apps
    op.drop_index(
        "ix_user_app_deployments_user_app_id", table_name="user_app_deployments"
    )
    op.drop_index(
        "ix_user_app_deployments_app_created", table_name="user_app_deployments"
    )
    op.drop_table("user_app_deployments")

    op.drop_index("ix_app_items_data", table_name="app_items", postgresql_using="gin")
    op.drop_index(op.f("ix_app_items_app_id"), table_name="app_items")
    op.drop_table("app_items")

    op.drop_index("ix_user_apps_user_visibility", table_name="user_apps")
    op.drop_index("ix_user_apps_user_status", table_name="user_apps")
    op.drop_index("ix_user_apps_user_name", table_name="user_apps")
    op.drop_index(op.f("ix_user_apps_user_id"), table_name="user_apps")
    op.drop_table("user_apps")


def downgrade() -> None:
    # Recreate user_apps
    op.create_table(
        "user_apps",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=10), nullable=True),
        sa.Column("template", sa.String(length=50), nullable=True),
        sa.Column(
            "schema_def", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("app_url", sa.String(length=500), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "visibility",
            sa.String(length=20),
            server_default="private",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_apps_user_id"), "user_apps", ["user_id"])
    op.create_index(
        "ix_user_apps_user_name", "user_apps", ["user_id", "name"], unique=True
    )
    op.create_index(
        "ix_user_apps_user_status", "user_apps", ["user_id", "status"]
    )
    op.create_index(
        "ix_user_apps_user_visibility", "user_apps", ["user_id", "visibility"]
    )

    # Recreate app_items
    op.create_table(
        "app_items",
        sa.Column("app_id", sa.UUID(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["app_id"], ["user_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_items_app_id"), "app_items", ["app_id"])
    op.create_index(
        "ix_app_items_data", "app_items", ["data"], postgresql_using="gin"
    )

    # Recreate user_app_deployments
    op.create_table(
        "user_app_deployments",
        sa.Column("user_app_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_deployment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "deployment_mode",
            sa.String(length=20),
            server_default="preview",
            nullable=False,
        ),
        sa.Column("deployment_target", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("generated_slug", sa.String(length=200), nullable=False),
        sa.Column("bundle_cache_key", sa.String(length=300), nullable=False),
        sa.Column("cloudflare_project_name", sa.String(length=100), nullable=True),
        sa.Column("deployment_url", sa.String(length=500), nullable=True),
        sa.Column("alias_url", sa.String(length=500), nullable=True),
        sa.Column("live_url", sa.String(length=500), nullable=True),
        sa.Column("bundle_kind", sa.String(length=50), nullable=True),
        sa.Column("framework", sa.String(length=50), nullable=True),
        sa.Column("generation_provider", sa.String(length=50), nullable=True),
        sa.Column("build_output_dir", sa.String(length=300), nullable=True),
        sa.Column("build_command", sa.String(length=300), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_deployment_id"],
            ["user_app_deployments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_app_id"], ["user_apps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_app_deployments_app_created",
        "user_app_deployments",
        ["user_app_id", "created_at"],
    )
    op.create_index(
        "ix_user_app_deployments_user_app_id",
        "user_app_deployments",
        ["user_app_id"],
    )
