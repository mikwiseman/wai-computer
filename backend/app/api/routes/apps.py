"""Collections API — CRUD for user-created mini-apps and their data."""

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Database
from app.models.user_app import AppItem, UserApp, UserAppDeployment
from app.services.user_apps import (
    apply_build_result_to_app,
    promote_generated_user_app,
    publish_user_app,
    record_user_app_deployment,
    touch_user_app,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps", tags=["apps"])


# ── Response Models ──────────────────────────────────────────────────

class AppResponse(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None
    icon: str | None
    template: str | None
    schema_def: dict | None
    app_url: str | None
    settings: dict | None
    status: Literal["draft", "live", "archived"]
    visibility: Literal["private", "unlisted", "public"]
    published_at: datetime | None
    last_used_at: datetime | None
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


class AppDeploymentResponse(BaseModel):
    id: str
    source_deployment_id: str | None
    deployment_mode: Literal["preview", "production"]
    deployment_target: str
    status: str
    generated_slug: str
    bundle_cache_key: str
    cloudflare_project_name: str | None
    deployment_url: str | None
    alias_url: str | None
    live_url: str | None
    bundle_kind: str | None
    framework: str | None
    generation_provider: str | None
    build_output_dir: str | None
    build_command: str | None
    created_at: datetime


# ── Request Models ───────────────────────────────────────────────────

class CreateAppRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = None
    template: str | None = None
    schema_def: dict | None = None
    settings: dict | None = None
    visibility: Literal["private", "unlisted", "public"] = "private"


class UpdateAppRequest(BaseModel):
    display_name: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = None
    schema_def: dict | None = None
    app_url: str | None = None
    settings: dict | None = None
    status: Literal["draft", "live", "archived"] | None = None
    visibility: Literal["private", "unlisted", "public"] | None = None
    sort_order: int | None = None


class CreateItemRequest(BaseModel):
    data: dict


class UpdateItemRequest(BaseModel):
    data: dict


class PublishAppRequest(BaseModel):
    visibility: Literal["private", "unlisted", "public"] = "private"
    app_url: str | None = None
    promote_preview: bool = True


class RollbackAppRequest(BaseModel):
    deployment_id: UUID
    visibility: Literal["private", "unlisted", "public"] | None = None


# ── App Endpoints ────────────────────────────────────────────────────

@router.post("", response_model=AppResponse, status_code=status.HTTP_201_CREATED)
async def create_app(request: CreateAppRequest, user: CurrentUser, db: Database) -> AppResponse:
    """Create a new user app (collection)."""
    logger.info("creating app user_id=%s name=%s", user.id, request.name)
    existing = await db.execute(
        select(UserApp).where(UserApp.user_id == user.id, UserApp.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="App name already exists")

    app = UserApp(
        user_id=user.id,
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        icon=request.icon,
        template=request.template,
        schema_def=request.schema_def,
        settings=request.settings,
        visibility=request.visibility,
    )
    db.add(app)
    await db.flush()  # needed to populate DB-generated defaults (id, sort_order, created_at)

    return _app_to_response(app, item_count=0)


@router.get("", response_model=list[AppResponse])
async def list_apps(
    user: CurrentUser,
    db: Database,
    app_status: Literal["draft", "live", "archived"] | None = Query(default=None, alias="status"),
    visibility: Literal["private", "unlisted", "public"] | None = None,
) -> list[AppResponse]:
    """List all user apps with item counts."""
    logger.info(
        "listing apps user_id=%s status=%s visibility=%s",
        user.id,
        app_status,
        visibility,
    )
    query = (
        select(UserApp, func.count(AppItem.id).label("item_count"))
        .outerjoin(AppItem, AppItem.app_id == UserApp.id)
        .where(UserApp.user_id == user.id)
        .group_by(UserApp.id)
    )
    if app_status is not None:
        query = query.where(UserApp.status == app_status)
    if visibility is not None:
        query = query.where(UserApp.visibility == visibility)

    result = await db.execute(
        query.order_by(
            UserApp.sort_order,
            UserApp.published_at.desc().nullslast(),
            UserApp.created_at.desc(),
        )
    )
    rows = result.all()

    return [_app_to_response(app, item_count=count) for app, count in rows]


@router.get("/{app_id}", response_model=AppResponse)
async def get_app(app_id: UUID, user: CurrentUser, db: Database) -> AppResponse:
    """Get app details."""
    app = await _get_user_app(db, user.id, app_id)
    touch_user_app(app)
    count_result = await db.execute(
        select(func.count()).where(AppItem.app_id == app.id)
    )
    count = count_result.scalar() or 0

    return _app_to_response(app, item_count=count)


@router.patch("/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: UUID, request: UpdateAppRequest, user: CurrentUser, db: Database
) -> AppResponse:
    """Update app schema/settings."""
    app = await _get_user_app(db, user.id, app_id)

    if request.display_name is not None:
        app.display_name = request.display_name
    if request.description is not None:
        app.description = request.description
    if request.icon is not None:
        app.icon = request.icon
    if request.schema_def is not None:
        app.schema_def = request.schema_def
    if request.app_url is not None:
        app.app_url = request.app_url
    if request.settings is not None:
        app.settings = request.settings
    if request.status is not None:
        app.status = request.status
        if request.status == "live" and app.published_at is None:
            app.published_at = datetime.now(UTC)
    if request.visibility is not None:
        app.visibility = request.visibility
    if request.sort_order is not None:
        app.sort_order = request.sort_order

    touch_user_app(app)
    await db.flush()  # needed to persist changes before count query
    logger.info("updated app user_id=%s app_id=%s status=%s", user.id, app.id, app.status)

    count_result = await db.execute(select(func.count()).where(AppItem.app_id == app.id))
    return _app_to_response(app, item_count=count_result.scalar() or 0)


@router.post("/{app_id}/publish", response_model=AppResponse)
async def publish_app(
    app_id: UUID,
    request: PublishAppRequest,
    user: CurrentUser,
    db: Database,
) -> AppResponse:
    """Publish an app and make it easy to share."""
    app = await _get_user_app(db, user.id, app_id)
    live_url = request.app_url
    if request.promote_preview and live_url is None:
        promote_result = await promote_generated_user_app(db, app)
        if not promote_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=promote_result.get("error", "Publish deploy failed"),
            )
        apply_build_result_to_app(app, promote_result)
        live_url = promote_result.get("url")

    publish_user_app(app, visibility=request.visibility, app_url=live_url)
    logger.info(
        "published app user_id=%s app_id=%s visibility=%s app_url=%s",
        user.id,
        app.id,
        app.visibility,
        app.app_url,
    )

    count_result = await db.execute(select(func.count()).where(AppItem.app_id == app.id))
    return _app_to_response(app, item_count=count_result.scalar() or 0)


@router.get("/{app_id}/deployments", response_model=list[AppDeploymentResponse])
async def list_app_deployments(
    app_id: UUID,
    user: CurrentUser,
    db: Database,
) -> list[AppDeploymentResponse]:
    """List deployment history for an app."""
    app = await _get_user_app(db, user.id, app_id)
    touch_user_app(app)
    result = await db.execute(
        select(UserAppDeployment)
        .where(UserAppDeployment.user_app_id == app.id)
        .order_by(UserAppDeployment.created_at.desc())
    )
    return [_deployment_to_response(row) for row in result.scalars().all()]


@router.post("/{app_id}/rollback", response_model=AppResponse)
async def rollback_app(
    app_id: UUID,
    request: RollbackAppRequest,
    user: CurrentUser,
    db: Database,
) -> AppResponse:
    """Rollback an app to a previously generated deployment bundle."""
    app = await _get_user_app(db, user.id, app_id)
    touch_user_app(app)

    deployment = await _get_app_deployment(db, app.id, request.deployment_id)
    from app.services.agent.app_builder import publish_cached_bundle

    result = await publish_cached_bundle(
        deployment.bundle_cache_key,
        project_name=deployment.cloudflare_project_name or "",
        slug=deployment.generated_slug,
        deployment_target=deployment.deployment_target,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "Rollback deploy failed"),
        )

    result.setdefault("bundle_cache_key", deployment.bundle_cache_key)
    result.setdefault("project_name", deployment.cloudflare_project_name)
    result.setdefault("bundle_kind", deployment.bundle_kind)
    result.setdefault("framework", deployment.framework)
    result.setdefault("generation_provider", deployment.generation_provider)
    apply_build_result_to_app(app, result)
    publish_user_app(
        app,
        visibility=request.visibility or app.visibility,
        app_url=result.get("url"),
    )
    await record_user_app_deployment(
        db,
        app,
        result,
        source_deployment_id=deployment.id,
    )

    count_result = await db.execute(select(func.count()).where(AppItem.app_id == app.id))
    return _app_to_response(app, item_count=count_result.scalar() or 0)


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
    touch_user_app(app)
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
    touch_user_app(app)
    item = AppItem(app_id=app.id, data=request.data)
    db.add(item)
    await db.flush()  # needed to populate DB-generated defaults (id, created_at, updated_at)
    logger.info("created app item user_id=%s app_id=%s item_id=%s", user.id, app.id, item.id)

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
    touch_user_app(app)
    result = await db.execute(
        select(AppItem).where(AppItem.id == item_id, AppItem.app_id == app.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item.data = request.data
    await db.flush()  # needed to get updated updated_at from DB
    await db.refresh(item)
    logger.info("updated app item user_id=%s app_id=%s item_id=%s", user.id, app.id, item.id)

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
    touch_user_app(app)
    result = await db.execute(
        select(AppItem).where(AppItem.id == item_id, AppItem.app_id == app.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await db.delete(item)
    logger.info("deleted app item user_id=%s app_id=%s item_id=%s", user.id, app.id, item.id)


@router.get("/{app_id}/stats", response_model=AppStatsResponse)
async def get_app_stats(app_id: UUID, user: CurrentUser, db: Database) -> AppStatsResponse:
    """Get aggregated stats for an app."""
    app = await _get_user_app(db, user.id, app_id)
    touch_user_app(app)

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


async def _get_app_deployment(
    db,
    app_id: UUID,
    deployment_id: UUID,
) -> UserAppDeployment:
    result = await db.execute(
        select(UserAppDeployment).where(
            UserAppDeployment.id == deployment_id,
            UserAppDeployment.user_app_id == app_id,
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    if not deployment.cloudflare_project_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deployment is missing Cloudflare project metadata",
        )
    return deployment


def _app_to_response(app: UserApp, *, item_count: int = 0) -> AppResponse:
    return AppResponse(
        id=str(app.id),
        name=app.name,
        display_name=app.display_name,
        description=app.description,
        icon=app.icon,
        template=app.template,
        schema_def=app.schema_def,
        app_url=app.app_url,
        settings=app.settings,
        status=app.status,
        visibility=app.visibility,
        published_at=app.published_at,
        last_used_at=app.last_used_at,
        sort_order=app.sort_order,
        item_count=item_count,
        created_at=app.created_at,
    )


def _deployment_to_response(deployment: UserAppDeployment) -> AppDeploymentResponse:
    return AppDeploymentResponse(
        id=str(deployment.id),
        source_deployment_id=(
            str(deployment.source_deployment_id) if deployment.source_deployment_id else None
        ),
        deployment_mode=deployment.deployment_mode,
        deployment_target=deployment.deployment_target,
        status=deployment.status,
        generated_slug=deployment.generated_slug,
        bundle_cache_key=deployment.bundle_cache_key,
        cloudflare_project_name=deployment.cloudflare_project_name,
        deployment_url=deployment.deployment_url,
        alias_url=deployment.alias_url,
        live_url=deployment.live_url,
        bundle_kind=deployment.bundle_kind,
        framework=deployment.framework,
        generation_provider=deployment.generation_provider,
        build_output_dir=deployment.build_output_dir,
        build_command=deployment.build_command,
        created_at=deployment.created_at,
    )
