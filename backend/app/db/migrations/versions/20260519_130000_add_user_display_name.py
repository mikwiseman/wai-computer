"""historic user display_name revision retained for alembic continuity

Revision ID: 20260519_130000
Revises: 20260519_120000
Create Date: 2026-05-19 13:00:00.000000+00:00

The original migration added ``users.display_name``. That field was removed from
the current model in favor of first/last name identity fields, but some
databases recorded this revision before the migration file was dropped. Keep the
revision as a no-op so existing databases and fresh installs share one graph.
"""

from __future__ import annotations

revision = "20260519_130000"
down_revision = "20260519_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
