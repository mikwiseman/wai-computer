"""strip markdown wrappers from recording and highlight titles

Revision ID: 20260518_120000
Revises: 20260510_180000
Create Date: 2026-05-18 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_120000"
down_revision: Union[str, None] = "20260510_180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Characters LLMs sometimes wrap titles in: markdown emphasis/heading markers
# and quote characters. Postgres `btrim(text, chars)` removes any combination
# of these from both ends until none match, so `**"Title"**` becomes `Title`.
_WRAPPER_CHARS = """*_#"'`«»‹›"""


def upgrade() -> None:
    for table in ("recordings", "highlights"):
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET title = trim(btrim(title, :wrappers))
                WHERE title IS NOT NULL
                  AND title <> trim(btrim(title, :wrappers))
                  AND trim(btrim(title, :wrappers)) <> ''
                """
            ).bindparams(wrappers=_WRAPPER_CHARS)
        )


def downgrade() -> None:
    # Data cleanup: the original wrappers were AI-generated noise, no value in
    # restoring them.
    pass
