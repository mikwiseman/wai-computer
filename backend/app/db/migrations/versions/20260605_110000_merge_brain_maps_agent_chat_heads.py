"""merge brain maps and agent chat migration heads

Revision ID: 20260605_110000
Revises: 20260604_170000, 20260605_100000
Create Date: 2026-06-05 11:00:00.000000
"""

from typing import Sequence, Union

revision: str = "20260605_110000"
down_revision: Union[str, tuple[str, str], None] = (
    "20260604_170000",
    "20260605_100000",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
