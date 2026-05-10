"""fix anthropic dictation model id

Revision ID: 20260508_150000
Revises: 20260508_120000
Create Date: 2026-05-08 15:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260508_150000"
down_revision: Union[str, None] = "20260508_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_MODEL = "claude-haiku-4-5"
NEW_MODEL = "claude-3-5-haiku-20241022"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET dictation_post_filter_model = :new_model "
            "WHERE dictation_post_filter_model = :old_model"
        ).bindparams(new_model=NEW_MODEL, old_model=OLD_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=NEW_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET dictation_post_filter_model = :old_model "
            "WHERE dictation_post_filter_model = :new_model"
        ).bindparams(new_model=NEW_MODEL, old_model=OLD_MODEL)
    )
    op.alter_column(
        "users",
        "dictation_post_filter_model",
        server_default=OLD_MODEL,
        existing_type=sa.String(100),
        existing_nullable=False,
    )
