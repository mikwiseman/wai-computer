"""Add missing indexes and fix missing server_defaults on UUID primary keys

Revision ID: 000009
Revises: 000008
Create Date: 2026-03-17

Fixes:
- Missing indexes on entity_relations (source_id, target_id, recording_id)
- Missing index on recording_tags (tag_id)
- Missing server_default on highlights.id, chat_sessions.id, chat_messages.id
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "000009"
down_revision: Union[str, None] = "000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing indexes on entity_relations foreign keys
    op.create_index("ix_entity_relations_source_id", "entity_relations", ["source_id"])
    op.create_index("ix_entity_relations_target_id", "entity_relations", ["target_id"])
    op.create_index("ix_entity_relations_recording_id", "entity_relations", ["recording_id"])

    # Add missing index on recording_tags.tag_id
    # (recording_id is already covered by the composite PK index)
    op.create_index("ix_recording_tags_tag_id", "recording_tags", ["tag_id"])

    # Fix missing server_default on UUID primary keys
    # Migrations 000003 and dc79b7dd96c1 omitted gen_random_uuid() on their id columns,
    # while all tables in 000001 correctly have it.
    for table in ("highlights", "chat_sessions", "chat_messages"):
        op.alter_column(
            table,
            "id",
            existing_type=postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
        )


def downgrade() -> None:
    for table in ("chat_messages", "chat_sessions", "highlights"):
        op.alter_column(
            table,
            "id",
            existing_type=postgresql.UUID(),
            server_default=None,
        )
    op.drop_index("ix_recording_tags_tag_id", table_name="recording_tags")
    op.drop_index("ix_entity_relations_recording_id", table_name="entity_relations")
    op.drop_index("ix_entity_relations_target_id", table_name="entity_relations")
    op.drop_index("ix_entity_relations_source_id", table_name="entity_relations")
