"""Cloudflare deployment helpers.

Supports both Cloudflare Pages and Cloudflare Workers Static Assets.

- Pages remains the compatibility target for simple static previews.
- Workers Static Assets is the preferred target for richer generated apps/sites
  because it matches Cloudflare's current full-stack direction more closely.
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Mapping

from app.config import get_settings

logger = logging.getLogger(__name__)

PROJECT_NAME_PREFIX = "wai"
WORKERS_COMPATIBILITY_DATE = "2026-04-01"


def _sanitize_output(text: str) -> str:
    """Strip Cloudflare credentials from error output to prevent leaks."""
    settings = get_settings()
    sanitized = text
    if settings.cloudflare_api_token:
        sanitized = sanitized.replace(settings.cloudflare_api_token, "[REDACTED]")
    if settings.cloudflare_account_id:
        sanitized = sanitized.replace(settings.cloudflare_account_id, "[REDACTED]")
    return sanitized


def project_name_for_slug(slug: str, *, kind: str = "site", unique_key: str | None = None) -> str:
    """Build a Cloudflare Pages project name.

    Cloudflare project names are shared at the account level, so we fold a
    short unique key into generated apps/sites when available.
    """
    normalized_slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower())
    normalized_slug = re.sub(r"-+", "-", normalized_slug).strip("-") or kind
    normalized_kind = re.sub(r"[^a-z0-9-]+", "-", kind.lower())
    normalized_kind = re.sub(r"-+", "-", normalized_kind).strip("-") or "site"
    normalized_key = ""
    if unique_key:
        normalized_key = re.sub(r"[^a-z0-9]+", "", unique_key.lower())[:10]

    project_name = f"{PROJECT_NAME_PREFIX}-{normalized_kind}-{normalized_slug}"
    if normalized_key:
        project_name = f"{project_name}-{normalized_key}"

    project_name = re.sub(r"-+", "-", project_name).strip("-")
    return project_name[:58].strip("-") or f"{PROJECT_NAME_PREFIX}-{normalized_kind}"


def live_url_for_project(project_name: str) -> str:
    """Return the production Pages URL for a project."""
    return f"https://{project_name}.pages.dev"


def worker_name_for_slug(slug: str, *, kind: str = "site", unique_key: str | None = None) -> str:
    """Build a Cloudflare Worker script name.

    We keep the same naming scheme as Pages so the generated URL is predictable.
    """
    return project_name_for_slug(slug, kind=kind, unique_key=unique_key)


def preview_worker_name(worker_name: str) -> str:
    """Derive a stable preview Worker name for a live script."""
    preview_name = f"{worker_name}-preview"
    return preview_name[:63].strip("-") or f"{worker_name[:55]}-preview"


def live_url_for_worker(worker_name: str) -> str:
    """Best-effort public workers.dev URL for a Worker script."""
    return f"https://{worker_name}.workers.dev"


async def deploy_to_cloudflare_pages(
    slug: str,
    html_content: str,
    *,
    branch: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Deploy HTML to Cloudflare Pages via wrangler CLI.

    When ``branch`` is provided, Cloudflare creates or updates a preview alias
    instead of replacing the production deployment for the shared Pages project.
    """
    return await deploy_bundle_to_cloudflare_pages(
        slug,
        {"index.html": html_content},
        branch=branch,
        project_name=project_name,
    )


async def deploy_bundle_to_cloudflare_pages(
    slug: str,
    files: Mapping[str, str],
    *,
    branch: str | None = None,
    build_config: dict | None = None,
    project_name: str | None = None,
) -> dict:
    """Deploy a file bundle to Cloudflare Pages.

    If ``build_config`` is provided, commands run inside the temporary project
    directory and the configured output directory is deployed instead.
    """
    settings = get_settings()
    token = settings.cloudflare_api_token
    account_id = settings.cloudflare_account_id
    if not token or not account_id:
        return {"success": False, "error": "Cloudflare credentials not configured"}

    resolved_project_name = project_name or project_name_for_slug(slug)

    env = {
        **os.environ,
        "CLOUDFLARE_API_TOKEN": token,
        "CLOUDFLARE_ACCOUNT_ID": account_id,
    }

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_bundle(project_dir, files)

            deploy_dir = project_dir
            build_output_dir = None
            if build_config and build_config.get("command"):
                install_command = build_config.get("install_command")
                build_command = build_config["command"]
                build_output_dir = str(build_config.get("output_dir") or "dist")

                if install_command:
                    install_result = await _run_shell_command(
                        install_command,
                        cwd=project_dir,
                        env=env,
                        timeout=240,
                    )
                    if install_result["returncode"] != 0:
                        return {
                            "success": False,
                            "error": f"Install error: {_sanitize_output((install_result['stderr'] or install_result['stdout'])[:400])}",
                        }

                build_result = await _run_shell_command(
                    build_command,
                    cwd=project_dir,
                    env=env,
                    timeout=240,
                )
                if build_result["returncode"] != 0:
                    return {
                        "success": False,
                        "error": f"Build error: {_sanitize_output((build_result['stderr'] or build_result['stdout'])[:400])}",
                    }

                deploy_dir = project_dir / build_output_dir
                if not deploy_dir.exists():
                    return {
                        "success": False,
                        "error": f"Build output directory not found: {build_output_dir}",
                    }

            ensure_result = await _ensure_pages_project(
                resolved_project_name,
                env=env,
            )
            if not ensure_result["success"]:
                return ensure_result

            deploy_result = await _run_pages_deploy(
                deploy_dir,
                env=env,
                branch=branch,
                slug=slug,
                project_name=resolved_project_name,
            )
            if not deploy_result["success"]:
                return deploy_result

            if build_output_dir:
                deploy_result["build_output_dir"] = build_output_dir
                deploy_result["build_command"] = build_config["command"]
            return deploy_result

    except asyncio.TimeoutError:
        logger.error("Wrangler deploy timed out after 60s")
        return {"success": False, "error": "Deploy timed out"}
    except Exception as e:
        logger.error(f"Cloudflare deploy error: {e}", exc_info=True)
        return {"success": False, "error": _sanitize_output(str(e))}


async def publish_bundle_to_cloudflare_pages(
    slug: str,
    files: Mapping[str, str],
    *,
    project_name: str,
    build_config: dict | None = None,
) -> dict:
    """Publish a bundle to the live root deployment for a Pages project."""
    return await deploy_bundle_to_cloudflare_pages(
        slug,
        files,
        branch=None,
        build_config=build_config,
        project_name=project_name,
    )


async def deploy_bundle_to_cloudflare_workers(
    slug: str,
    files: Mapping[str, str],
    *,
    branch: str | None = None,
    build_config: dict | None = None,
    worker_name: str | None = None,
) -> dict:
    """Deploy a bundle to Cloudflare Workers Static Assets.

    Preview deployments use a second stable worker name rather than a branch.
    """
    settings = get_settings()
    token = settings.cloudflare_api_token
    account_id = settings.cloudflare_account_id
    if not token or not account_id:
        return {"success": False, "error": "Cloudflare credentials not configured"}

    resolved_worker_name = worker_name or worker_name_for_slug(slug)
    target_worker_name = preview_worker_name(resolved_worker_name) if branch else resolved_worker_name
    env = {
        **os.environ,
        "CLOUDFLARE_API_TOKEN": token,
        "CLOUDFLARE_ACCOUNT_ID": account_id,
    }

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_bundle(project_dir, files)

            deploy_dir = project_dir
            build_output_dir = None
            if build_config and build_config.get("command"):
                install_command = build_config.get("install_command")
                build_command = build_config["command"]
                build_output_dir = str(build_config.get("output_dir") or "dist")

                if install_command:
                    install_result = await _run_shell_command(
                        install_command,
                        cwd=project_dir,
                        env=env,
                        timeout=240,
                    )
                    if install_result["returncode"] != 0:
                        return {
                            "success": False,
                            "error": f"Install error: {_sanitize_output((install_result['stderr'] or install_result['stdout'])[:400])}",
                        }

                build_result = await _run_shell_command(
                    build_command,
                    cwd=project_dir,
                    env=env,
                    timeout=240,
                )
                if build_result["returncode"] != 0:
                    return {
                        "success": False,
                        "error": f"Build error: {_sanitize_output((build_result['stderr'] or build_result['stdout'])[:400])}",
                    }

                deploy_dir = project_dir / build_output_dir
                if not deploy_dir.exists():
                    return {
                        "success": False,
                        "error": f"Build output directory not found: {build_output_dir}",
                    }

            config_path = _write_workers_static_assets_config(
                project_dir,
                deploy_dir=deploy_dir,
                worker_name=target_worker_name,
            )

            deploy_result = await _run_workers_deploy(
                project_dir,
                config_path=config_path,
                env=env,
                worker_name=target_worker_name,
                live_worker_name=resolved_worker_name,
                slug=slug,
                branch=branch,
            )
            if not deploy_result["success"]:
                return deploy_result

            if build_output_dir:
                deploy_result["build_output_dir"] = build_output_dir
                deploy_result["build_command"] = build_config["command"]
            return deploy_result
    except asyncio.TimeoutError:
        logger.error("Wrangler workers deploy timed out after 60s")
        return {"success": False, "error": "Deploy timed out"}
    except Exception as e:
        logger.error("Cloudflare workers deploy error: %s", e, exc_info=True)
        return {"success": False, "error": _sanitize_output(str(e))}


async def publish_bundle_to_cloudflare_workers(
    slug: str,
    files: Mapping[str, str],
    *,
    worker_name: str,
    build_config: dict | None = None,
) -> dict:
    """Publish a bundle to the live workers.dev URL for a Worker script."""
    return await deploy_bundle_to_cloudflare_workers(
        slug,
        files,
        branch=None,
        build_config=build_config,
        worker_name=worker_name,
    )


def _write_bundle(root: Path, files: Mapping[str, str]) -> None:
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _write_workers_static_assets_config(
    project_dir: Path,
    *,
    deploy_dir: Path,
    worker_name: str,
) -> Path:
    """Write a minimal Wrangler config for static-assets deployment.

    We generate our own config so preview and live worker names are deterministic
    without mutating user bundle files.
    """
    relative_assets_dir = os.path.relpath(deploy_dir, project_dir).replace("\\", "/")
    config = {
        "name": worker_name,
        "compatibility_date": WORKERS_COMPATIBILITY_DATE or date.today().isoformat(),
        "assets": {
            "directory": relative_assets_dir,
            "not_found_handling": "single-page-application",
        },
        "observability": {"enabled": True},
    }
    config_path = project_dir / "wrangler.generated.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


async def _run_shell_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> dict:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
    }


async def _run_pages_deploy(
    deploy_dir: Path,
    *,
    env: dict[str, str],
    branch: str | None,
    slug: str,
    project_name: str,
) -> dict:
    command = [
        "wrangler",
        "pages",
        "deploy",
        str(deploy_dir),
        f"--project-name={project_name}",
        "--commit-dirty=true",
    ]
    if branch:
        command.append(f"--branch={branch}")

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode != 0:
        error = _sanitize_output((stderr_text or stdout_text)[:300])
        logger.error("Wrangler deploy failed (exit %s): %s", proc.returncode, error)
        return {"success": False, "error": f"Deploy error: {error}"}

    deploy_url = ""
    alias_url = ""
    for line in stdout_text.splitlines():
        if "https://" in line and ".pages.dev" in line:
            candidate = line.strip().split()[-1]
            if "Deployment alias URL:" in line:
                alias_url = candidate
            elif not deploy_url:
                deploy_url = candidate

    if branch:
        final_url = alias_url or deploy_url or live_url_for_project(project_name)
    else:
        final_url = live_url_for_project(project_name)
    result = {
        "success": True,
        "url": final_url,
        "slug": slug,
        "project_name": project_name,
    }
    if branch:
        result["branch"] = branch
    if deploy_url:
        result["deployment_url"] = deploy_url
    if alias_url:
        result["alias_url"] = alias_url

    logger.info(
        "Cloudflare deploy OK branch=%s url=%s deployment_url=%s alias_url=%s",
        branch,
        final_url,
        deploy_url or "",
        alias_url or "",
    )
    return result


async def _run_workers_deploy(
    project_dir: Path,
    *,
    config_path: Path,
    env: dict[str, str],
    worker_name: str,
    live_worker_name: str,
    slug: str,
    branch: str | None,
) -> dict:
    command = [
        "wrangler",
        "deploy",
        f"--config={config_path}",
    ]

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode != 0:
        error = _sanitize_output((stderr_text or stdout_text)[:300])
        logger.error("Wrangler workers deploy failed (exit %s): %s", proc.returncode, error)
        return {"success": False, "error": f"Deploy error: {error}"}

    worker_url = ""
    for line in stdout_text.splitlines():
        if "https://" in line and ".workers.dev" in line:
            candidate = line.strip().split()[-1]
            if candidate.startswith("https://"):
                worker_url = candidate
                break

    if not worker_url:
        worker_url = live_url_for_worker(worker_name)

    result = {
        "success": True,
        "url": worker_url,
        "slug": slug,
        "project_name": live_worker_name,
        "deployment_url": worker_url,
    }
    if branch:
        result["branch"] = branch
        result["alias_url"] = worker_url

    logger.info(
        "Cloudflare workers deploy OK branch=%s url=%s worker=%s",
        branch,
        worker_url,
        worker_name,
    )
    return result


async def _ensure_pages_project(
    project_name: str,
    *,
    env: dict[str, str],
) -> dict:
    """Create a Pages project if it doesn't already exist."""
    command = [
        "wrangler",
        "pages",
        "project",
        "create",
        project_name,
        "--production-branch=main",
    ]
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    stdout_text = stdout.decode()
    stderr_text = stderr.decode()

    if proc.returncode == 0:
        logger.info("Cloudflare Pages project ready project=%s created=true", project_name)
        return {"success": True, "project_name": project_name}

    combined = "\n".join(part for part in (stdout_text, stderr_text) if part).lower()
    if "already exists" in combined:
        logger.info("Cloudflare Pages project ready project=%s created=false", project_name)
        return {"success": True, "project_name": project_name}

    error = _sanitize_output((stderr_text or stdout_text)[:300])
    logger.error("Cloudflare Pages project create failed project=%s error=%s", project_name, error)
    return {"success": False, "error": f"Project create error: {error}"}
