"""User model."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    default_language: Mapped[str] = mapped_column(
        String(10), default="multi", server_default="multi"
    )
    summary_language: Mapped[str] = mapped_column(
        String(10), default="auto", server_default="auto"
    )
    summary_style: Mapped[str] = mapped_column(
        String(20), default="medium", server_default="medium"
    )
    summary_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    recordings: Mapped[list["Recording"]] = relationship(
        "Recording", back_populates="user", cascade="all, delete-orphan"
    )
    folders: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="user", cascade="all, delete-orphan"
    )
    entities: Mapped[list["Entity"]] = relationship(
        "Entity", back_populates="user", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="user", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="user", cascade="all, delete-orphan"
    )


# Import at bottom to avoid circular imports
from app.models.chat import ChatSession  # noqa: E402
from app.models.entity import Entity, Tag  # noqa: E402
from app.models.recording import Folder, Recording  # noqa: E402
