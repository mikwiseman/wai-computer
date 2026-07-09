"""change users.accent server default from teal to amber

The product default accent is amber (web ThemeAccentPicker DEFAULT_ACCENT and
Mac MacThemePreferences.defaultAccent both use amber), but the column shipped
with server_default 'teal'. Fresh users flipped to teal the moment the web
settings screen hydrated server preferences. Align the column default with the
product. Existing rows are left untouched — a stored 'teal' may be a deliberate
user choice.

Revision ID: 20260709_144403
Revises: 20260707_223000
Create Date: 2026-07-09 14:44:03.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_144403"
down_revision: Union[str, tuple[str, str], None] = "20260707_223000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "accent",
        server_default="amber",
        existing_type=sa.String(length=12),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "accent",
        server_default="teal",
        existing_type=sa.String(length=12),
        existing_nullable=False,
    )
