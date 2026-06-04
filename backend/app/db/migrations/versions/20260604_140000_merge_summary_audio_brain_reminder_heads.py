"""merge summary audio and brain/reminder migration heads

Revision ID: 20260604_140000
Revises: 20260604_120000, 20260604_130000
Create Date: 2026-06-04 14:00:00.000000
"""

from typing import Sequence, Union

revision: str = "20260604_140000"
down_revision: Union[str, None] = ("20260604_120000", "20260604_130000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
