"""Entity and knowledge graph models."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Entity(Base, UUIDMixin, TimestampMixin):
    """Entity model for people, topics, projects in the knowledge graph."""

    __tablename__ = "entities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # person, topic, project
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))

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
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # mentioned_in, works_on, related_to
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recordings.id", ondelete="SET NULL")
    )
    context: Mapped[str | None] = mapped_column(Text)

    # Relationships
    source: Mapped["Entity"] = relationship(
        "Entity", back_populates="source_relations", foreign_keys=[source_id]
    )
    target: Mapped["Entity"] = relationship(
        "Entity", back_populates="target_relations", foreign_keys=[target_id]
    )


class Tag(Base, UUIDMixin):
    """Tag for organizing recordings."""

    __tablename__ = "tags"

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
    )

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="recordings")


# Import at bottom to avoid circular imports
from app.models.user import User
from app.models.recording import Recording
