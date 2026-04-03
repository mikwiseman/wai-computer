"""Direct handler coverage for app lifecycle routes."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.api.routes.apps as apps_routes
from app.api.routes.apps import (
    AppDeploymentResponse,
    CreateAppRequest,
    CreateItemRequest,
    PublishAppRequest,
    RollbackAppRequest,
    UpdateAppRequest,
    UpdateItemRequest,
    create_app,
    create_item,
    delete_app,
    delete_item,
    get_app,
    get_app_stats,
    list_app_deployments,
    list_apps,
    list_items,
    publish_app,
    rollback_app,
    update_app,
    update_item,
)
from app.models.user import User
from app.models.user_app import UserApp, UserAppDeployment


@pytest.fixture
def fake_user():
    user_id = uuid4()
    return SimpleNamespace(id=user_id)


@pytest.mark.asyncio
async def test_app_route_lifecycle_handlers(db_session, fake_user):
    db_user = User(id=fake_user.id, email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(db_user)
    await db_session.flush()

    created = await create_app(
        CreateAppRequest(
            name="habits",
            display_name="Habits",
            description="Track habits",
            visibility="private",
        ),
        fake_user,
        db_session,
    )
    assert created.name == "habits"
    assert created.status == "draft"

    listed = await list_apps(fake_user, db_session, app_status=None, visibility=None)
    assert len(listed) == 1

    app_id = UUID(created.id)

    fetched = await get_app(app_id, fake_user, db_session)
    assert fetched.description == "Track habits"

    updated = await update_app(
        app_id,
        UpdateAppRequest(
            display_name="Habits 2",
            description="Track more habits",
            icon="🔥",
            schema_def={"type": "object", "properties": {"habit": {"type": "string"}}},
            app_url="https://draft-habits.wai.computer",
            settings={"theme": "sunrise"},
            status="live",
            visibility="unlisted",
            sort_order=7,
        ),
        fake_user,
        db_session,
    )
    assert updated.display_name == "Habits 2"
    assert updated.icon == "🔥"
    assert updated.schema_def == {"type": "object", "properties": {"habit": {"type": "string"}}}
    assert updated.app_url == "https://draft-habits.wai.computer"
    assert updated.settings == {"theme": "sunrise"}
    assert updated.status == "live"
    assert updated.sort_order == 7
    assert updated.published_at is not None

    published = await publish_app(
        app_id,
        PublishAppRequest(
            visibility="public",
            app_url="https://habits.wai.computer",
        ),
        fake_user,
        db_session,
    )
    assert published.visibility == "public"
    assert published.app_url == "https://habits.wai.computer"

    item = await create_item(
        app_id,
        CreateItemRequest(data={"habit": "meditation", "done": False}),
        fake_user,
        db_session,
    )
    assert item.data["habit"] == "meditation"

    items = await list_items(app_id, fake_user, db_session, limit=10, offset=0)
    assert len(items) == 1

    updated_item = await update_item(
        app_id,
        UUID(item.id),
        UpdateItemRequest(data={"habit": "meditation", "done": True}),
        fake_user,
        db_session,
    )
    assert updated_item.data["done"] is True

    stats = await get_app_stats(app_id, fake_user, db_session)
    assert stats.total_items == 1

    await delete_item(app_id, UUID(item.id), fake_user, db_session)
    items_after_delete = await list_items(app_id, fake_user, db_session, limit=10, offset=0)
    assert items_after_delete == []

    await delete_app(app_id, fake_user, db_session)
    with pytest.raises(HTTPException, match="App not found"):
        await get_app(app_id, fake_user, db_session)


@pytest.mark.asyncio
async def test_app_route_handlers_cover_error_paths(db_session, fake_user):
    db_user = User(id=fake_user.id, email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(db_user)
    await db_session.flush()

    await create_app(
        CreateAppRequest(name="dupe", display_name="Dupe"),
        fake_user,
        db_session,
    )

    with pytest.raises(HTTPException, match="App name already exists"):
        await create_app(
            CreateAppRequest(name="dupe", display_name="Duplicate"),
            fake_user,
            db_session,
        )

    listed = await list_apps(fake_user, db_session, app_status="live", visibility="public")
    assert listed == []

    with pytest.raises(HTTPException, match="App not found"):
        await get_app(uuid4(), fake_user, db_session)


@pytest.mark.asyncio
async def test_delete_item_raises_not_found_for_missing_item(db_session, fake_user):
    db_user = User(id=fake_user.id, email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(db_user)
    await db_session.flush()

    created = await create_app(
        CreateAppRequest(name="missing-item", display_name="Missing Item"),
        fake_user,
        db_session,
    )

    with pytest.raises(HTTPException, match="Item not found"):
        await delete_item(UUID(created.id), uuid4(), fake_user, db_session)


@pytest.mark.asyncio
async def test_publish_handler_promotes_preview_when_no_url_supplied(
    db_session,
    fake_user,
    monkeypatch,
):
    db_user = User(id=fake_user.id, email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(db_user)
    await db_session.flush()

    app = UserApp(
        user_id=fake_user.id,
        name="preview-app",
        display_name="Preview App",
        app_url="https://preview.preview-app.pages.dev",
        settings={
            "bundle_cache_key": "site:preview-app",
            "cloudflare_project_name": "wai-site-preview-app",
            "generated_slug": "preview-app",
        },
    )
    db_session.add(app)
    await db_session.flush()

    async def fake_promote(db, target_app):
        assert target_app.id == app.id
        target_app.app_url = "https://wai-site-preview-app.pages.dev"
        return {
            "success": True,
            "url": "https://wai-site-preview-app.pages.dev",
            "deployment_mode": "production",
            "deployment_target": "cloudflare-pages",
            "project_name": "wai-site-preview-app",
        }

    monkeypatch.setattr(apps_routes, "promote_generated_user_app", fake_promote)

    published = await publish_app(
        UUID(str(app.id)),
        PublishAppRequest(visibility="public"),
        fake_user,
        db_session,
    )

    assert published.status == "live"
    assert published.visibility == "public"
    assert published.app_url == "https://wai-site-preview-app.pages.dev"


@pytest.mark.asyncio
async def test_deployment_history_and_rollback_handlers(db_session, fake_user, monkeypatch):
    db_user = User(id=fake_user.id, email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(db_user)
    await db_session.flush()

    app = UserApp(
        user_id=fake_user.id,
        name="rollback-app",
        display_name="Rollback App",
        status="live",
        visibility="public",
        app_url="https://wai-site-rollback-app.pages.dev",
        settings={
            "generated_slug": "rollback-app",
            "cloudflare_project_name": "wai-site-rollback-app",
            "bundle_cache_key": "site:rollback-app:v:current",
        },
    )
    db_session.add(app)
    await db_session.flush()

    deployment = UserAppDeployment(
        user_app_id=app.id,
        deployment_mode="preview",
        deployment_target="cloudflare-pages",
        status="succeeded",
        generated_slug="rollback-app",
        bundle_cache_key="site:rollback-app:v:old",
        cloudflare_project_name="wai-site-rollback-app",
        alias_url="https://preview-rollback.pages.dev",
        bundle_kind="vite-react-site",
        framework="react-vite",
        generation_provider="claude-code",
    )
    db_session.add(deployment)
    await db_session.flush()

    history = await list_app_deployments(UUID(str(app.id)), fake_user, db_session)
    assert len(history) == 1
    assert isinstance(history[0], AppDeploymentResponse)
    assert history[0].bundle_cache_key == "site:rollback-app:v:old"

    async def fake_publish_cached_bundle(cache_key, *, project_name, slug, deployment_target):
        assert cache_key == "site:rollback-app:v:old"
        assert project_name == "wai-site-rollback-app"
        assert slug == "rollback-app"
        assert deployment_target == "cloudflare-pages"
        return {
            "success": True,
            "url": "https://wai-site-rollback-app.pages.dev",
            "deployment_mode": "production",
            "deployment_target": "cloudflare-pages",
            "deployment_url": "https://deploy.pages.dev",
            "project_name": "wai-site-rollback-app",
            "bundle_cache_key": "site:rollback-app:v:old",
            "bundle_kind": "vite-react-site",
            "framework": "react-vite",
            "generation_provider": "claude-code",
        }

    monkeypatch.setattr(
        "app.services.agent.app_builder.publish_cached_bundle",
        fake_publish_cached_bundle,
    )

    rolled_back = await rollback_app(
        UUID(str(app.id)),
        RollbackAppRequest(deployment_id=deployment.id, visibility="unlisted"),
        fake_user,
        db_session,
    )

    assert rolled_back.status == "live"
    assert rolled_back.visibility == "unlisted"
    assert rolled_back.app_url == "https://wai-site-rollback-app.pages.dev"
