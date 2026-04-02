"""fix user app deployment timestamp defaults

Revision ID: 20260401_203000
Revises: 20260401_190000
Create Date: 2026-04-01 20:30:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260401_203000"
down_revision: Union[str, None] = "20260401_190000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE user_app_deployments
            SET created_at = COALESCE(created_at, now()),
                updated_at = COALESCE(updated_at, now())
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )
    )
    op.alter_column(
        "user_app_deployments",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=False,
    )
    op.alter_column(
        "user_app_deployments",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_app_deployments",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "user_app_deployments",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        existing_nullable=False,
    )
