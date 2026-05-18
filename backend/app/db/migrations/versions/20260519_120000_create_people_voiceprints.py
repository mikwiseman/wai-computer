"""create people and voiceprints tables; add speaker assignment columns to segments

Revision ID: 20260519_120000
Revises: 20260518_200000
Create Date: 2026-05-19 12:00:00.000000+00:00

Adds the editable-speaker data model:

- ``people``: per-user address book of known speakers.
- ``voiceprints``: 1..N voice embedding samples per Person (ECAPA-TDNN, 192-d).
- ``segments.raw_label``: immutable STT label (e.g. "Speaker 0"); backfilled from
  the existing ``speaker`` column for historical rows.
- ``segments.person_id``: per-recording assignment to a Person (renders as the
  display name; falls back to ``raw_label`` when NULL).
- ``segments.auto_assigned`` + ``segments.match_confidence``: bookkeeping for
  voice-ID-driven assignments so re-matching can skip user-confirmed rows.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260519_120000"
down_revision: Union[str, None] = "20260518_200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("aliases", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_people_user_id", "people", ["user_id"])

    op.create_table(
        "voiceprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(192), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column(
            "source_recording_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_voiceprints_person_id", "voiceprints", ["person_id"])
    op.create_index("ix_voiceprints_user_id", "voiceprints", ["user_id"])
    op.execute(
        "CREATE INDEX ix_voiceprints_embedding ON voiceprints "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.add_column("segments", sa.Column("raw_label", sa.String(100), nullable=True))
    op.add_column(
        "segments",
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "segments",
        sa.Column(
            "auto_assigned",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("segments", sa.Column("match_confidence", sa.Float, nullable=True))
    op.create_index("ix_segments_person_id", "segments", ["person_id"])

    op.execute("UPDATE segments SET raw_label = speaker WHERE speaker IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_segments_person_id", table_name="segments")
    op.drop_column("segments", "match_confidence")
    op.drop_column("segments", "auto_assigned")
    op.drop_column("segments", "person_id")
    op.drop_column("segments", "raw_label")

    op.execute("DROP INDEX IF EXISTS ix_voiceprints_embedding")
    op.drop_index("ix_voiceprints_user_id", table_name="voiceprints")
    op.drop_index("ix_voiceprints_person_id", table_name="voiceprints")
    op.drop_table("voiceprints")

    op.drop_index("ix_people_user_id", table_name="people")
    op.drop_table("people")
