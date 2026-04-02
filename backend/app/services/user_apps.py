"""User app lifecycle helpers."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_app import UserApp, UserAppDeployment

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug[:80] or "app"


async def ensure_unique_app_name(
    db: AsyncSession,
    user_id: UUID,
    desired_name: str,
) -> str:
    """Return a per-user unique app slug."""
    base_name = _slugify(desired_name)
    candidate = base_name
    suffix = 2

    while True:
        result = await db.execute(
            select(UserApp.id).where(UserApp.user_id == user_id, UserApp.name == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base_name}-{suffix}"
        suffix += 1


async def create_generated_user_app(
    db: AsyncSession,
    user_id: UUID,
    description: str,
    build_result: dict,
    *,
    template: str = "custom",
    theme: str | None = None,
) -> UserApp:
    """Persist a generated app so it shows up in the user's app library."""
    now = datetime.now(UTC)
    name = await ensure_unique_app_name(
        db,
        user_id,
        build_result.get("slug") or description[:80] or "app",
    )
    is_live = bool(
        build_result.get("success")
        and build_result.get("url")
        and build_result.get("deployment_mode") == "production"
    )

    settings: dict[str, object] = {
        "builder": "wai",
        "generated_slug": build_result.get("slug") or name,
        "html_cached": bool(build_result.get("html_cached")),
    }
    optional_settings = {
        "artifact_mode": build_result.get("artifact_mode"),
        "bundle_kind": build_result.get("bundle_kind"),
        "framework": build_result.get("framework"),
        "deployment_target": build_result.get("deployment_target"),
        "deployment_mode": build_result.get("deployment_mode"),
        "deployment_branch": build_result.get("deployment_branch"),
        "deployment_url": build_result.get("deployment_url"),
        "alias_url": build_result.get("alias_url"),
        "live_url": build_result.get("live_url"),
        "cloudflare_project_name": build_result.get("project_name"),
        "bundle_cache_key": build_result.get("bundle_cache_key"),
        "generation_provider": build_result.get("generation_provider"),
        "build_output_dir": build_result.get("build_output_dir"),
        "build_command": build_result.get("build_command"),
        "site_key": build_result.get("site_key"),
    }
    settings.update({key: value for key, value in optional_settings.items() if value is not None})
    if theme:
        settings["theme"] = theme

    app = UserApp(
        user_id=user_id,
        name=name,
        display_name=(description.strip() or name.replace("-", " ").title())[:200],
        description=description[:2000] or None,
        template=template,
        app_url=build_result.get("url"),
        settings=settings,
        status="live" if is_live else "draft",
        visibility="private",
        published_at=now if is_live else None,
        last_used_at=now,
    )
    db.add(app)
    await db.flush()
    await record_user_app_deployment(db, app, build_result)
    logger.info(
        "generated user app persisted user_id=%s app_id=%s name=%s status=%s",
        user_id,
        app.id,
        app.name,
        app.status,
    )
    return app


def publish_user_app(
    app: UserApp,
    *,
    visibility: str | None = None,
    app_url: str | None = None,
) -> UserApp:
    """Mark an app as live and update shareable metadata."""
    now = datetime.now(UTC)
    app.status = "live"
    app.published_at = now
    app.last_used_at = now
    if visibility is not None:
        app.visibility = visibility
    if app_url is not None:
        app.app_url = app_url
    logger.info(
        "user app published app_id=%s visibility=%s has_url=%s",
        app.id,
        app.visibility,
        bool(app.app_url),
    )
    return app


def apply_build_result_to_app(app: UserApp, build_result: dict) -> UserApp:
    """Merge deployment/build metadata into app settings."""
    settings = dict(app.settings or {})
    generated_slug = build_result.get("slug") or settings.get("generated_slug") or app.name
    bundle_cache_key = build_result.get("bundle_cache_key", settings.get("bundle_cache_key"))
    bundle_pointer_key = build_result.get(
        "bundle_pointer_key",
        settings.get("bundle_pointer_key"),
    )
    settings.update(
        {
            "generated_slug": generated_slug,
            "artifact_mode": build_result.get("artifact_mode", settings.get("artifact_mode")),
            "bundle_kind": build_result.get("bundle_kind", settings.get("bundle_kind")),
            "framework": build_result.get("framework", settings.get("framework")),
            "deployment_target": build_result.get(
                "deployment_target",
                settings.get("deployment_target"),
            ),
            "deployment_mode": build_result.get("deployment_mode", settings.get("deployment_mode")),
            "deployment_branch": build_result.get(
                "deployment_branch",
                settings.get("deployment_branch"),
            ),
            "deployment_url": build_result.get("deployment_url", settings.get("deployment_url")),
            "alias_url": build_result.get("alias_url", settings.get("alias_url")),
            "live_url": build_result.get("live_url", settings.get("live_url")),
            "cloudflare_project_name": build_result.get(
                "project_name",
                settings.get("cloudflare_project_name"),
            ),
            "bundle_cache_key": bundle_cache_key,
            "bundle_pointer_key": bundle_pointer_key,
            "generation_provider": build_result.get(
                "generation_provider",
                settings.get("generation_provider"),
            ),
            "build_output_dir": build_result.get(
                "build_output_dir",
                settings.get("build_output_dir"),
            ),
            "build_command": build_result.get("build_command", settings.get("build_command")),
        }
    )
    app.settings = {key: value for key, value in settings.items() if value is not None}
    return app


async def record_user_app_deployment(
    db: AsyncSession,
    app: UserApp,
    build_result: dict,
    *,
    source_deployment_id: UUID | None = None,
) -> UserAppDeployment | None:
    """Persist a deployment event for preview, publish, or rollback."""
    if not build_result.get("success"):
        return None

    settings = app.settings or {}
    deployment_mode = build_result.get("deployment_mode") or settings.get("deployment_mode")
    deployment_target = (
        build_result.get("deployment_target")
        or settings.get("deployment_target")
        or "cloudflare-pages"
    )
    generated_slug = build_result.get("slug") or settings.get("generated_slug") or app.name
    bundle_cache_key = build_result.get("bundle_cache_key") or settings.get("bundle_cache_key")
    cloudflare_project_name = (
        build_result.get("project_name")
        or settings.get("cloudflare_project_name")
    )
    if not deployment_mode or not deployment_target or not bundle_cache_key:
        return None

    timestamp = datetime.now(UTC)
    deployment = UserAppDeployment(
        user_app_id=app.id,
        source_deployment_id=source_deployment_id,
        deployment_mode=str(deployment_mode),
        deployment_target=str(deployment_target),
        status="succeeded",
        generated_slug=str(generated_slug),
        bundle_cache_key=str(bundle_cache_key),
        cloudflare_project_name=(
            str(cloudflare_project_name) if cloudflare_project_name is not None else None
        ),
        deployment_url=build_result.get("deployment_url"),
        alias_url=build_result.get("alias_url"),
        live_url=build_result.get("live_url") or (
            build_result.get("url") if build_result.get("deployment_mode") == "production" else None
        ),
        bundle_kind=build_result.get("bundle_kind"),
        framework=build_result.get("framework"),
        generation_provider=build_result.get("generation_provider"),
        build_output_dir=build_result.get("build_output_dir"),
        build_command=build_result.get("build_command"),
    )
    deployment.created_at = timestamp
    deployment.updated_at = timestamp
    db.add(deployment)
    await db.flush()
    logger.info(
        "user app deployment recorded app_id=%s deployment_id=%s mode=%s target=%s",
        app.id,
        deployment.id,
        deployment.deployment_mode,
        deployment.deployment_target,
    )
    return deployment


async def promote_generated_user_app(
    db: AsyncSession,
    app: UserApp,
    *,
    source_deployment_id: UUID | None = None,
) -> dict:
    """Deploy the cached preview bundle to the app's live Pages URL."""
    settings = app.settings or {}
    cache_key = settings.get("bundle_cache_key")
    project_name = settings.get("cloudflare_project_name")
    slug = settings.get("generated_slug") or app.name

    if not isinstance(cache_key, str) or not cache_key:
        return {"success": False, "error": "Bundle cache key is missing"}
    if not isinstance(project_name, str) or not project_name:
        return {"success": False, "error": "Cloudflare project name is missing"}

    from app.services.agent.app_builder import publish_cached_bundle

    result = await publish_cached_bundle(
        cache_key,
        project_name=project_name,
        slug=slug,
        deployment_target=str(settings.get("deployment_target") or "cloudflare-pages"),
    )
    if result.get("success"):
        apply_build_result_to_app(app, result)
        app.app_url = result.get("url")
        await record_user_app_deployment(
            db,
            app,
            result,
            source_deployment_id=source_deployment_id,
        )
    return result


def touch_user_app(app: UserApp) -> UserApp:
    """Update usage timestamp for sorting/relevance."""
    app.last_used_at = datetime.now(UTC)
    return app
