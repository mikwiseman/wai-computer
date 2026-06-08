"""Make users.email nullable for Telegram-only signup; add signup_origin

Telegram-only accounts are keyed by telegram_user_id and have no email until the
user opts to add one. Replace the full UNIQUE(email) constraint with a PARTIAL
unique index (WHERE email IS NOT NULL) so many emailless users can coexist while
real emails stay unique.

Revision ID: 20260608_120000
Revises: 20260607_150000
Create Date: 2026-06-08 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_120000"
down_revision: Union[str, tuple[str, str], None] = "20260607_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the full unique constraint; keep the plain ix_users_email lookup index.
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    # Real emails stay unique; multiple NULLs (Telegram-only accounts) are allowed.
    op.create_index(
        "uq_users_email_not_null",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.add_column("users", sa.Column("signup_origin", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "signup_origin")
    op.drop_index("uq_users_email_not_null", table_name="users")
    # NB: fails if any NULL-email (Telegram-only) rows exist — resolve them first.
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)
    op.create_unique_constraint("users_email_key", "users", ["email"])
