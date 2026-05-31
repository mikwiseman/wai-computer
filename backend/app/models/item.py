"""Universal "item" models — any non-recording content in the second brain.

An ``Item`` is the canonical record for anything that is not an audio
``Recording``: a web article, a PDF, a forwarded link (YouTube / Instagram /
TikTok / X), a pasted note, an email, a calendar event, or a row pulled from
a connected MCP server. Items share the same downstream machinery as
recordings — ``Summary`` / ``ActionItem`` / ``Highlight`` / ``Entity`` and the
hybrid search index — so the rest of the app sees a unified second brain.

``ItemChunk`` mirrors ``Segment``: it stores embedded text chunks (with a
contextual header) so an item participates in semantic + lexical search.

Design notes:
- ``content_hash`` is a SHA-256 of the normalised body; ``(user_id,
  content_hash)`` is unique so re-forwarding the same link never re-ingests
  or re-transcribes (idempotency / cost control).
- ``simhash`` is a 64-bit near-duplicate fingerprint for cheap fuzzy dedup.
- ``state`` is ``raw`` on ingest (signal-capture-first) and may become
  ``promoted`` once the consolidator lifts durable facts into memory.
- Free-string ``source`` / ``kind`` / ``state`` / ``privacy_level`` (no DB
  enums) mirror ``Recording.type`` and keep migrations cheap as we add types.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.recording import Folder
    from app.models.user import User


class Item(Base, UUIDMixin, TimestampMixin):
    """Any non-recording piece of content in the user's second brain."""

    __tablename__ = "items"
    __table_args__ = (
        # Idempotency: the same content for a user is ingested once.
        UniqueConstraint("user_id", "content_hash", name="uq_items_user_content_hash"),
        Index("ix_items_user_created", "user_id", "created_at"),
        Index("ix_items_user_occurred", "user_id", "occurred_at"),
        Index("ix_items_user_source", "user_id", "source"),
        Index("ix_items_user_kind", "user_id", "kind"),
        Index("ix_items_user_state", "user_id", "state"),
        Index("ix_items_simhash", "simhash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provenance: where it came from and a stable external id/uri.
    # source: upload | url | paste | telegram | mcp:<connection_id>
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(1000))
    url: Mapped[str | None] = mapped_column(String(2000))

    # kind: article | video | post | pdf | email | note | event | message | transaction | ...
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="note")

    title: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)

    # When the content itself happened (publish/sent date); feed falls back to
    # created_at when null. created_at (TimestampMixin) is the ingestion time.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Dedup fingerprints.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simhash: Mapped[int | None] = mapped_column(BigInteger)

    # Governance / ranking signals.
    privacy_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default="internal"
    )
    authority_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    salience_score: Mapped[float | None] = mapped_column(Float)
    # state: raw (searchable, in feed) -> promoted (facts lifted to memory)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="raw", server_default="raw"
    )

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    # A single document-level embedding (chunk-level lives on ItemChunk).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship("User")
    folder: Mapped["Folder | None"] = relationship("Folder")
    chunks: Mapped[list["ItemChunk"]] = relationship(
        "ItemChunk",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    summary: Mapped["ItemSummary | None"] = relationship(
        "ItemSummary",
        back_populates="item",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ItemSummary(Base, UUIDMixin, TimestampMixin):
    """The AI summary + key-moments table for one Item.

    Items reuse the same structured-summary *shape* as recordings (summary,
    key_points, decisions, action_items, topics, people_mentioned, highlights,
    sentiment) but store it here as JSONB rather than across the
    recordings-only ``summaries`` / ``action_items`` / ``highlights`` tables —
    keeping those production tables untouched. ``key_moments`` is the hero
    "forward -> table" output (one row per moment).
    """

    __tablename__ = "item_summaries"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_item_summaries_item"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[list | None] = mapped_column(JSONB)
    decisions: Mapped[list | None] = mapped_column(JSONB)
    action_items: Mapped[list | None] = mapped_column(JSONB)
    topics: Mapped[list | None] = mapped_column(JSONB)
    people_mentioned: Mapped[list | None] = mapped_column(JSONB)
    highlights: Mapped[list | None] = mapped_column(JSONB)
    key_moments: Mapped[list | None] = mapped_column(JSONB)
    sentiment: Mapped[str | None] = mapped_column(String(20))

    item: Mapped["Item"] = relationship("Item", back_populates="summary")


class ItemChunk(Base, UUIDMixin):
    """An embedded text chunk of an Item (mirrors Segment for recordings)."""

    __tablename__ = "item_chunks"
    __table_args__ = (
        Index("ix_item_chunks_item_id", "item_id"),
        UniqueConstraint("item_id", "seq", name="uq_item_chunks_item_seq"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Order of the chunk within the item.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Embedded text, prefixed with a contextual header ("title › section").
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="chunks")
