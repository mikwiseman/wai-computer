"""add theme and accent to users

Revision ID: 20260527_120000
Revises: 20260526_110000
Create Date: 2026-05-27 12:00:00.000000+00:00

Adds per-user UI preferences:
- theme: system | light | dark (default 'system')
- accent: teal | amber | blue | green | violet | rose | graphite (default 'teal')

Both columns use ADD COLUMN ... NOT NULL DEFAULT in a single statement.
On Postgres >= 11 this is a metadata-only operation and safe for large tables.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_120000"
down_revision: Union[str, None] = "20260526_110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "theme",
            sa.String(length=10),
            server_default="system",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "accent",
            sa.String(length=12),
            server_default="teal",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "accent")
    op.drop_column("users", "theme")
