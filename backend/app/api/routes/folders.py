"""Folder routes for organizing recordings."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.models.item import Item
from app.models.recording import Folder

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderResponse(BaseModel):
    """Response for a folder."""

    id: str
    name: str
    created_at: datetime


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


def _serialize_folder(folder: Folder) -> FolderResponse:
    return FolderResponse(id=str(folder.id), name=folder.name, created_at=folder.created_at)


@router.get("", response_model=list[FolderResponse])
async def list_folders(user: CurrentUser, db: Database) -> list[FolderResponse]:
    """List folders for the current user."""
    result = await db.execute(
        select(Folder)
        .where(Folder.user_id == user.id)
        .order_by(Folder.name.asc(), Folder.created_at.asc())
    )
    return [_serialize_folder(folder) for folder in result.scalars().all()]


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


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
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

    await db.delete(folder)
    await db.flush()
