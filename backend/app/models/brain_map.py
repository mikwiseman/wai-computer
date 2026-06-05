"""Live Brain Maps: durable recipes plus immutable generated revisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BrainMap(Base, UUIDMixin, TimestampMixin):
    """A saved lens over the user's Brain.

    The map stores the user's intent and layout overrides. Generated claims,
    nodes, edges, citations, and diffs live in immutable ``BrainMapRevision``
    rows so refreshes can stay auditable.
    """

    __tablename__ = "brain_maps"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_brain_maps_user_status", "user_id", "status"),
        Index("ix_brain_maps_user_updated", "user_id", "updated_at"),
        Index("ix_brain_maps_space", "space_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_spaces.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    map_type: Mapped[str] = mapped_column(String(40), nullable=False)
    origin: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="brain",
        server_default="brain",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    source_scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrainMapRevision(Base, UUIDMixin, TimestampMixin):
    """One generated projection of a Brain Map at a source fingerprint."""

    __tablename__ = "brain_map_revisions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("map_id", "revision_index", name="uq_brain_map_revisions_map_idx"),
        Index("ix_brain_map_revisions_map", "map_id"),
        Index("ix_brain_map_revisions_user_compiled", "user_id", "compiled_at"),
        Index("ix_brain_map_revisions_fingerprint", "map_id", "source_fingerprint"),
    )

    map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brain_maps.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_index: Mapped[int] = mapped_column(Integer, nullable=False)
    projection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    freshness: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
