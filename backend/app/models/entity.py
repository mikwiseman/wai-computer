"""Entity and knowledge graph models."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Entity(Base, UUIDMixin, TimestampMixin):
    """Entity model for people, topics, projects in the knowledge graph."""

    __tablename__ = "entities"
    __table_args__ = (
        # Exact dedup key for the upsert path (fuzzy duplicates go to Review,
        # never a silent merge).
        UniqueConstraint("user_id", "type", "name", name="uq_entities_user_type_name"),
        # GIN index for strong-identity-key lookups (metadata @> {identity_keys:[...]})
        # so resolving an emailer to an existing person stays cheap at scale.
        Index("ix_entities_metadata_gin", "metadata", postgresql_using="gin"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # person, topic, project
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="entities")
    source_relations: Mapped[list["EntityRelation"]] = relationship(
        "EntityRelation",
        back_populates="source",
        foreign_keys="EntityRelation.source_id",
        cascade="all, delete-orphan",
    )
    target_relations: Mapped[list["EntityRelation"]] = relationship(
        "EntityRelation",
        back_populates="target",
        foreign_keys="EntityRelation.target_id",
        cascade="all, delete-orphan",
    )


class EntityRelation(Base, UUIDMixin):
    """Relation between entities (knowledge graph edge)."""

    __tablename__ = "entity_relations"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # mentioned_in, works_on, related_to
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="SET NULL"),
        index=True,
    )
    context: Mapped[str | None] = mapped_column(Text)

    # Relationships
    source: Mapped["Entity"] = relationship(
        "Entity", back_populates="source_relations", foreign_keys=[source_id]
    )
    target: Mapped["Entity"] = relationship(
        "Entity", back_populates="target_relations", foreign_keys=[target_id]
    )


class EntityMention(Base, UUIDMixin, TimestampMixin):
    """A mention of an entity by a source — recording OR item (polymorphic).

    The join that makes "any material in one brain" real at the graph layer: an
    article / PDF / video / recording links to every entity it mentions.
    ``source_id`` is polymorphic (no FK); ``source_kind`` says which table it
    points at. ``EntityRelation`` stays the entity->entity edge; this is the
    source->entity provenance edge.
    """

    __tablename__ = "entity_mentions"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "source_kind",
            "source_id",
            name="uq_entity_mentions_entity_source",
        ),
        Index("ix_entity_mentions_entity", "entity_id"),
        Index("ix_entity_mentions_user_source", "user_id", "source_kind", "source_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    # source_kind: "recording" | "item" | "chat". source_id is polymorphic (no FK).
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Optional finer-grained provenance (a segment / item_chunk).
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    context: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )


class EntityPageSnapshot(Base, UUIDMixin, TimestampMixin):
    """Generated wiki-style snapshot for an entity page."""

    __tablename__ = "entity_page_snapshots"
    __table_args__ = (
        UniqueConstraint("entity_id", name="uq_entity_page_snapshots_entity"),
        Index("ix_entity_page_snapshots_user_id", "user_id"),
        Index("ix_entity_page_snapshots_entity_id", "entity_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    overview: Mapped[str] = mapped_column(Text, nullable=False)
    facts: Mapped[list] = mapped_column(JSONB, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False)
    timeline: Mapped[list] = mapped_column(JSONB, nullable=False)
    related_explanations: Mapped[list] = mapped_column(JSONB, nullable=False)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User")
    entity: Mapped["Entity"] = relationship("Entity")


class EntityFact(Base, UUIDMixin, TimestampMixin):
    """A bi-temporal asserted fact: (subject) predicate (object) with a validity
    window. Unlike EntityRelation (a typed co-mention edge) this is a stated fact
    about the world. CURRENT iff ``invalid_at IS NULL``; supersession CLOSES the
    window (sets ``invalid_at`` + ``superseded_by_id``) and never deletes — so
    "what's true now" is a query and history is preserved (Graphiti supersede-not-
    delete; mem0-v3 keep-history, done safely). ``created_at`` (TimestampMixin) is
    ingest/transaction time; ``valid_at``/``invalid_at`` is world time."""

    __tablename__ = "entity_facts"
    __table_args__ = (
        # At most ONE *current* fact per (subject, predicate, object); superseded
        # (invalid) rows are exempt, so a fact can be re-asserted after it was
        # invalidated. The leading (user_id, subject_entity_id) columns also serve
        # the load-current-facts-for-a-subject query.
        Index(
            "uq_entity_facts_current_triple",
            "user_id",
            "subject_entity_id",
            "predicate",
            "object_text",
            unique=True,
            postgresql_where=text("invalid_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predicate: Mapped[str] = mapped_column(String(100), nullable=False)  # lowercase snake_case
    object_text: Mapped[str] = mapped_column(Text, nullable=False)
    object_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL")
    )
    # Provenance (polymorphic, like EntityMention): which source asserted the fact.
    source_kind: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    importance: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_facts.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Tag(Base, UUIDMixin):
    """Tag for organizing recordings."""

    __tablename__ = "tags"
    # Note: unique constraint deferred — migration 000010 removed due to deploy issues

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tags")
    recordings: Mapped[list["RecordingTag"]] = relationship(
        "RecordingTag", back_populates="tag", cascade="all, delete-orphan"
    )


class RecordingTag(Base):
    """Many-to-many relationship between recordings and tags."""

    __tablename__ = "recording_tags"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="recordings")


# Import at bottom to avoid circular imports
from app.models.recording import Recording  # noqa: E402
from app.models.user import User  # noqa: E402
