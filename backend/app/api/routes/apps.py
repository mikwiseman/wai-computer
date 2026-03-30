"""Collections API — CRUD for user-created mini-apps and their data."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Database
from app.models.user_app import AppItem, UserApp

router = APIRouter(prefix="/apps", tags=["apps"])


# ── Response Models ──────────────────────────────────────────────────

class AppResponse(BaseModel):
    id: str
    name: str
    display_name: str
    icon: str | None
    template: str | None
    schema_def: dict | None
    app_url: str | None
    settings: dict | None
    sort_order: int
    item_count: int = 0
    created_at: datetime


class AppItemResponse(BaseModel):
    id: str
    data: dict
    created_at: datetime
    updated_at: datetime


class AppStatsResponse(BaseModel):
    app_id: str
    total_items: int
    created_at: datetime
    last_item_at: datetime | None


# ── Request Models ───────────────────────────────────────────────────

class CreateAppRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    icon: str | None = None
    template: str | None = None
    schema_def: dict | None = None
    settings: dict | None = None


class UpdateAppRequest(BaseModel):
    display_name: str | None = None
    icon: str | None = None
    schema_def: dict | None = None
    app_url: str | None = None
    settings: dict | None = None
    sort_order: int | None = None


class CreateItemRequest(BaseModel):
    data: dict


class UpdateItemRequest(BaseModel):
    data: dict


# ── App Endpoints ────────────────────────────────────────────────────

@router.post("", response_model=AppResponse, status_code=status.HTTP_201_CREATED)
async def create_app(request: CreateAppRequest, user: CurrentUser, db: Database) -> AppResponse:
    """Create a new user app (collection)."""
    existing = await db.execute(
        select(UserApp).where(UserApp.user_id == user.id, UserApp.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="App name already exists")

    app = UserApp(
        user_id=user.id,
        name=request.name,
        display_name=request.display_name,
        icon=request.icon,
        template=request.template,
        schema_def=request.schema_def,
        settings=request.settings,
    )
    db.add(app)
    await db.flush()

    return AppResponse(
        id=str(app.id), name=app.name, display_name=app.display_name,
        icon=app.icon, template=app.template, schema_def=app.schema_def,
        app_url=app.app_url, settings=app.settings, sort_order=app.sort_order,
        item_count=0, created_at=app.created_at,
    )


@router.get("", response_model=list[AppResponse])
async def list_apps(user: CurrentUser, db: Database) -> list[AppResponse]:
    """List all user apps with item counts."""
    result = await db.execute(
        select(UserApp, func.count(AppItem.id).label("item_count"))
        .outerjoin(AppItem, AppItem.app_id == UserApp.id)
        .where(UserApp.user_id == user.id)
        .group_by(UserApp.id)
        .order_by(UserApp.sort_order, UserApp.created_at.desc())
    )
    rows = result.all()

    return [
        AppResponse(
            id=str(app.id), name=app.name, display_name=app.display_name,
            icon=app.icon, template=app.template, schema_def=app.schema_def,
            app_url=app.app_url, settings=app.settings, sort_order=app.sort_order,
            item_count=count, created_at=app.created_at,
        )
        for app, count in rows
    ]


@router.get("/{app_id}", response_model=AppResponse)
async def get_app(app_id: UUID, user: CurrentUser, db: Database) -> AppResponse:
    """Get app details."""
    app = await _get_user_app(db, user.id, app_id)
    count_result = await db.execute(
        select(func.count()).where(AppItem.app_id == app.id)
    )
    count = count_result.scalar() or 0

    return AppResponse(
        id=str(app.id), name=app.name, display_name=app.display_name,
        icon=app.icon, template=app.template, schema_def=app.schema_def,
        app_url=app.app_url, settings=app.settings, sort_order=app.sort_order,
        item_count=count, created_at=app.created_at,
    )


@router.patch("/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: UUID, request: UpdateAppRequest, user: CurrentUser, db: Database
) -> AppResponse:
    """Update app schema/settings."""
    app = await _get_user_app(db, user.id, app_id)

    if request.display_name is not None:
        app.display_name = request.display_name
    if request.icon is not None:
        app.icon = request.icon
    if request.schema_def is not None:
        app.schema_def = request.schema_def
    if request.app_url is not None:
        app.app_url = request.app_url
    if request.settings is not None:
        app.settings = request.settings
    if request.sort_order is not None:
        app.sort_order = request.sort_order

    await db.flush()

    return AppResponse(
        id=str(app.id), name=app.name, display_name=app.display_name,
        icon=app.icon, template=app.template, schema_def=app.schema_def,
        app_url=app.app_url, settings=app.settings, sort_order=app.sort_order,
        created_at=app.created_at,
    )


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(app_id: UUID, user: CurrentUser, db: Database) -> None:
    """Delete app and all its items (cascade)."""
    app = await _get_user_app(db, user.id, app_id)
    await db.delete(app)


# ── Item Endpoints ───────────────────────────────────────────────────

@router.get("/{app_id}/items", response_model=list[AppItemResponse])
async def list_items(
    app_id: UUID, user: CurrentUser, db: Database,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AppItemResponse]:
    """List items in an app."""
    app = await _get_user_app(db, user.id, app_id)
    result = await db.execute(
        select(AppItem)
        .where(AppItem.app_id == app.id)
        .order_by(AppItem.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = result.scalars().all()

    return [
        AppItemResponse(
            id=str(item.id), data=item.data,
            created_at=item.created_at, updated_at=item.updated_at,
        )
        for item in items
    ]


@router.post("/{app_id}/items", response_model=AppItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    app_id: UUID, request: CreateItemRequest, user: CurrentUser, db: Database
) -> AppItemResponse:
    """Create an item in an app."""
    app = await _get_user_app(db, user.id, app_id)
    item = AppItem(app_id=app.id, data=request.data)
    db.add(item)
    await db.flush()

    return AppItemResponse(
        id=str(item.id), data=item.data,
        created_at=item.created_at, updated_at=item.updated_at,
    )


@router.patch("/{app_id}/items/{item_id}", response_model=AppItemResponse)
async def update_item(
    app_id: UUID, item_id: UUID, request: UpdateItemRequest,
    user: CurrentUser, db: Database,
) -> AppItemResponse:
    """Update an item's data."""
    app = await _get_user_app(db, user.id, app_id)
    result = await db.execute(
        select(AppItem).where(AppItem.id == item_id, AppItem.app_id == app.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item.data = request.data
    await db.flush()

    return AppItemResponse(
        id=str(item.id), data=item.data,
        created_at=item.created_at, updated_at=item.updated_at,
    )


@router.delete("/{app_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    app_id: UUID, item_id: UUID, user: CurrentUser, db: Database,
) -> None:
    """Delete an item."""
    app = await _get_user_app(db, user.id, app_id)
    result = await db.execute(
        select(AppItem).where(AppItem.id == item_id, AppItem.app_id == app.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await db.delete(item)


@router.get("/{app_id}/stats", response_model=AppStatsResponse)
async def get_app_stats(app_id: UUID, user: CurrentUser, db: Database) -> AppStatsResponse:
    """Get aggregated stats for an app."""
    app = await _get_user_app(db, user.id, app_id)

    count_result = await db.execute(
        select(func.count(), func.max(AppItem.created_at)).where(AppItem.app_id == app.id)
    )
    row = count_result.one()

    return AppStatsResponse(
        app_id=str(app.id),
        total_items=row[0] or 0,
        created_at=app.created_at,
        last_item_at=row[1],
    )


# ── Helpers ──────────────────────────────────────────────────────────

async def _get_user_app(db, user_id: UUID, app_id: UUID) -> UserApp:
    """Get a user's app or raise 404."""
    result = await db.execute(
        select(UserApp).where(UserApp.id == app_id, UserApp.user_id == user_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")
    return app
