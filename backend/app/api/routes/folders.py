"""Folder routes for organizing recordings, materials, and Wai chats."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.models.companion import Conversation
from app.models.item import Item
from app.models.recording import Folder, Recording

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderResponse(BaseModel):
    """Response for a folder."""

    id: str
    name: str
    created_at: datetime
    # Recordings, materials, and Wai chats currently filed in the folder
    # (trash excluded) — drives the sidebar counts on every client.
    item_count: int = 0


class CreateFolderRequest(BaseModel):
    """Request to create a folder."""

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Folder name cannot be empty")
        return normalized


class UpdateFolderRequest(CreateFolderRequest):
    """Request to rename a folder."""


def _serialize_folder(folder: Folder, item_count: int = 0) -> FolderResponse:
    return FolderResponse(
        id=str(folder.id),
        name=folder.name,
        created_at=folder.created_at,
        item_count=item_count,
    )


async def _folder_content_counts(db: Database, user_id: UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    recording_rows = await db.execute(
        select(Recording.folder_id, func.count())
        .where(
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
            Recording.folder_id.is_not(None),
        )
        .group_by(Recording.folder_id)
    )
    for folder_id, count in recording_rows.all():
        counts[str(folder_id)] = counts.get(str(folder_id), 0) + int(count)
    item_rows = await db.execute(
        select(Item.folder_id, func.count())
        .where(
            Item.user_id == user_id,
            Item.deleted_at.is_(None),
            Item.state.is_distinct_from("archived"),
            Item.folder_id.is_not(None),
        )
        .group_by(Item.folder_id)
    )
    for folder_id, count in item_rows.all():
        counts[str(folder_id)] = counts.get(str(folder_id), 0) + int(count)
    chat_rows = await db.execute(
        select(Conversation.folder_id, func.count())
        .where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
            Conversation.archived_at.is_(None),
            Conversation.folder_id.is_not(None),
        )
        .group_by(Conversation.folder_id)
    )
    for folder_id, count in chat_rows.all():
        counts[str(folder_id)] = counts.get(str(folder_id), 0) + int(count)
    return counts


@router.get("", response_model=list[FolderResponse])
async def list_folders(user: CurrentUser, db: Database) -> list[FolderResponse]:
    """List folders for the current user, with recording+material+chat counts."""
    result = await db.execute(
        select(Folder)
        .where(Folder.user_id == user.id)
        .order_by(Folder.name.asc(), Folder.created_at.asc())
    )
    counts = await _folder_content_counts(db, user.id)
    return [
        _serialize_folder(folder, counts.get(str(folder.id), 0))
        for folder in result.scalars().all()
    ]


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    request: CreateFolderRequest,
    user: CurrentUser,
    db: Database,
) -> FolderResponse:
    """Create a folder for the current user."""
    folder = Folder(user_id=user.id, name=request.name)
    db.add(folder)
    await db.flush()
    return _serialize_folder(folder)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: UUID,
    request: UpdateFolderRequest,
    user: CurrentUser,
    db: Database,
) -> FolderResponse:
    """Rename a folder."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
    )
    folder = result.scalar_one_or_none()

    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    folder.name = request.name
    await db.flush()
    return _serialize_folder(folder)


@router.delete(
    "/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_folder(
    folder_id: UUID,
    user: CurrentUser,
    db: Database,
) -> Response:
    """Delete a folder and unassign every inbox object in it."""
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id, Folder.user_id == user.id)
        .options(selectinload(Folder.recordings))
    )
    folder = result.scalar_one_or_none()

    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    for recording in folder.recordings:
        recording.folder_id = None

    item_result = await db.execute(
        select(Item).where(Item.user_id == user.id, Item.folder_id == folder.id)
    )
    for item in item_result.scalars().all():
        item.folder_id = None

    chat_result = await db.execute(
        select(Conversation).where(
            Conversation.user_id == user.id, Conversation.folder_id == folder.id
        )
    )
    for chat in chat_result.scalars().all():
        chat.folder_id = None

    await db.delete(folder)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
