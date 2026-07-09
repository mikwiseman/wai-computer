"""add recordings.capture_metadata for client capture sidecars

Native clients upload a compact JSON sidecar with each recording describing
how audio was captured (mono mix vs two-channel) and the merged intervals of
local-mic speech. Processing uses it to attribute the diarization cluster
that matches local speech to the device owner's self Person.

Revision ID: 20260709_120000
Revises: 20260709_144403
Create Date: 2026-07-09 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260709_120000"
down_revision: Union[str, tuple[str, str], None] = "20260709_144403"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("capture_metadata", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recordings", "capture_metadata")
