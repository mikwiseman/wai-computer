"""add lifecycle fields to user_apps

Revision ID: 20260401_130000
Revises: 869f5f0a48e5
Create Date: 2026-04-01 13:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260401_130000"
down_revision: Union[str, None] = "869f5f0a48e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_apps", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "user_apps",
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
    )
    op.add_column(
        "user_apps",
        sa.Column("visibility", sa.String(length=20), server_default="private", nullable=False),
    )
    op.add_column("user_apps", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_apps", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_user_apps_user_status", "user_apps", ["user_id", "status"], unique=False)
    op.create_index(
        "ix_user_apps_user_visibility",
        "user_apps",
        ["user_id", "visibility"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_apps_user_visibility", table_name="user_apps")
    op.drop_index("ix_user_apps_user_status", table_name="user_apps")
    op.drop_column("user_apps", "last_used_at")
    op.drop_column("user_apps", "published_at")
    op.drop_column("user_apps", "visibility")
    op.drop_column("user_apps", "status")
    op.drop_column("user_apps", "description")
