"""Tests for user app lifecycle helpers."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.user import User
from app.models.user_app import UserApp, UserAppDeployment
from app.services.user_apps import (
    apply_build_result_to_app,
    create_generated_user_app,
    ensure_unique_app_name,
    promote_generated_user_app,
    publish_user_app,
)


@pytest_asyncio.fixture
async def persisted_user(db_session):
    user = User(email=f"user-{uuid4().hex}@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_create_generated_user_app_persists_preview_metadata_as_draft(
    db_session,
    persisted_user,
):
    app = await create_generated_user_app(
        db_session,
        persisted_user.id,
        "Habit tracker for meditation and reading",
        {
            "success": True,
            "url": "https://preview-habits.wai-app-habits.pages.dev",
            "slug": "habits",
            "artifact_mode": "bundle",
            "bundle_kind": "vite-react-app",
            "framework": "react-vite",
            "deployment_mode": "preview",
            "deployment_branch": "preview-habits",
            "deployment_url": "https://deploy-preview.pages.dev",
            "alias_url": "https://preview-habits.wai-app-habits.pages.dev",
            "project_name": "wai-app-habits",
            "live_url": "https://wai-app-habits.pages.dev",
            "bundle_cache_key": "app-123",
            "build_output_dir": "dist",
            "build_command": "npm run build",
        },
        theme="calm",
    )

    assert app.status == "draft"
    assert app.visibility == "private"
    assert app.published_at is None
    assert app.last_used_at is not None
    assert app.settings["generated_slug"] == "habits"
    assert app.settings["theme"] == "calm"
    assert app.settings["artifact_mode"] == "bundle"
    assert app.settings["bundle_kind"] == "vite-react-app"
    assert app.settings["deployment_branch"] == "preview-habits"
    assert app.settings["cloudflare_project_name"] == "wai-app-habits"
    assert app.settings["bundle_cache_key"] == "app-123"
    deployments = (
        await db_session.execute(
            select(UserAppDeployment).where(UserAppDeployment.user_app_id == app.id)
        )
    ).scalars().all()
    assert len(deployments) == 1
    assert deployments[0].deployment_mode == "preview"
    assert deployments[0].cloudflare_project_name == "wai-app-habits"
    assert deployments[0].created_at is not None
    assert deployments[0].updated_at is not None


@pytest.mark.asyncio
async def test_ensure_unique_app_name_adds_suffix_when_needed(db_session, persisted_user):
    db_session.add(
        UserApp(
            user_id=persisted_user.id,
            name="habits",
            display_name="Habits",
        )
    )
    await db_session.flush()

    candidate = await ensure_unique_app_name(db_session, persisted_user.id, "habits")
    assert candidate == "habits-2"


@pytest.mark.asyncio
async def test_publish_user_app_updates_status_and_visibility(db_session, persisted_user):
    app = UserApp(
        user_id=persisted_user.id,
        name="draft-app",
        display_name="Draft App",
    )
    db_session.add(app)
    await db_session.flush()

    publish_user_app(
        app,
        visibility="public",
        app_url="https://draft-app.wai.computer",
    )
    await db_session.flush()

    refreshed = (
        await db_session.execute(select(UserApp).where(UserApp.id == app.id))
    ).scalar_one()
    assert refreshed.status == "live"
    assert refreshed.visibility == "public"
    assert refreshed.app_url == "https://draft-app.wai.computer"
    assert refreshed.published_at is not None


@pytest.mark.asyncio
async def test_apply_build_result_to_app_merges_settings(db_session, persisted_user):
    app = UserApp(
        user_id=persisted_user.id,
        name="site-app",
        display_name="Site App",
        settings={"theme": "warm"},
    )
    db_session.add(app)
    await db_session.flush()

    apply_build_result_to_app(
        app,
        {
            "slug": "site-app",
            "deployment_mode": "production",
            "deployment_url": "https://deploy.pages.dev",
            "project_name": "wai-site-site-app",
            "bundle_cache_key": "site:site-app",
            "url": "https://wai-site-site-app.pages.dev",
        },
    )

    assert app.settings["theme"] == "warm"
    assert app.settings["deployment_mode"] == "production"
    assert app.settings["cloudflare_project_name"] == "wai-site-site-app"
    assert app.settings["bundle_cache_key"] == "site:site-app"


@pytest.mark.asyncio
async def test_promote_generated_user_app_redeploys_live(monkeypatch, db_session, persisted_user):
    app = UserApp(
        user_id=persisted_user.id,
        name="site-app",
        display_name="Site App",
        status="draft",
        settings={
            "generated_slug": "site-app",
            "cloudflare_project_name": "wai-site-site-app",
            "bundle_cache_key": "site:site-app",
        },
    )
    db_session.add(app)
    await db_session.flush()

    async def fake_publish_cached_bundle(cache_key, *, project_name, slug, deployment_target):
        assert cache_key == "site:site-app"
        assert project_name == "wai-site-site-app"
        assert slug == "site-app"
        assert deployment_target == "cloudflare-pages"
        return {
            "success": True,
            "url": "https://wai-site-site-app.pages.dev",
            "deployment_mode": "production",
            "deployment_url": "https://deploy.pages.dev",
            "project_name": "wai-site-site-app",
        }

    monkeypatch.setattr(
        "app.services.agent.app_builder.publish_cached_bundle",
        fake_publish_cached_bundle,
    )

    result = await promote_generated_user_app(db_session, app)

    assert result["success"] is True
    assert app.app_url == "https://wai-site-site-app.pages.dev"
    assert app.settings["deployment_mode"] == "production"
    deployments = (
        await db_session.execute(
            select(UserAppDeployment).where(UserAppDeployment.user_app_id == app.id)
        )
    ).scalars().all()
    assert len(deployments) == 1
    assert deployments[0].deployment_mode == "production"
    assert deployments[0].created_at is not None
