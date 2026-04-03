"""Tests for Cloudflare deploy helper."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.cloudflare_deploy import (
    deploy_bundle_to_cloudflare_pages,
    deploy_bundle_to_cloudflare_workers,
    deploy_to_cloudflare_pages,
    live_url_for_project,
    live_url_for_worker,
    preview_worker_name,
    project_name_for_slug,
    publish_bundle_to_cloudflare_pages,
    publish_bundle_to_cloudflare_workers,
    worker_name_for_slug,
)


@pytest.mark.asyncio
async def test_deploy_to_cloudflare_pages_requires_credentials():
    with patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings:
        mock_settings.return_value.cloudflare_api_token = ""
        mock_settings.return_value.cloudflare_account_id = ""

        result = await deploy_to_cloudflare_pages("demo", "<html></html>")

    assert result == {"success": False, "error": "Cloudflare credentials not configured"}


@pytest.mark.asyncio
async def test_deploy_to_cloudflare_pages_parses_pages_url():
    create_proc = MagicMock()
    create_proc.returncode = 1
    create_proc.communicate = AsyncMock(return_value=(b"", b"project already exists"))

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(
        return_value=(
            b"Uploaded files\nhttps://demo-project.pages.dev\nDeployment alias URL: https://preview-demo.wai-site-demo.pages.dev\n",
            b"",
        )
    )

    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[create_proc, proc]),
        ) as mock_exec,
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_to_cloudflare_pages("demo", "<html></html>", branch="preview-demo")

    assert result == {
        "success": True,
        "url": "https://preview-demo.wai-site-demo.pages.dev",
        "slug": "demo",
        "project_name": "wai-site-demo",
        "branch": "preview-demo",
        "deployment_url": "https://demo-project.pages.dev",
        "alias_url": "https://preview-demo.wai-site-demo.pages.dev",
    }
    create_args = mock_exec.await_args_list[0].args
    deploy_args = mock_exec.await_args_list[1].args
    assert create_args[:4] == ("wrangler", "pages", "project", "create")
    assert deploy_args[:3] == ("wrangler", "pages", "deploy")
    assert "--branch=preview-demo" in deploy_args


@pytest.mark.asyncio
async def test_deploy_to_cloudflare_pages_surfaces_cli_error():
    create_proc = MagicMock()
    create_proc.returncode = 0
    create_proc.communicate = AsyncMock(return_value=(b"created", b""))

    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))

    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[create_proc, proc]),
        ),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_to_cloudflare_pages("demo", "<html></html>")

    assert result["success"] is False
    assert "permission denied" in result["error"]


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_pages_runs_build_pipeline():
    create_proc = MagicMock()
    create_proc.returncode = 0
    create_proc.communicate = AsyncMock(return_value=(b"created", b""))

    install_proc = MagicMock()
    install_proc.returncode = 0
    install_proc.communicate = AsyncMock(return_value=(b"installed", b""))

    build_proc = MagicMock()
    build_proc.returncode = 0
    build_proc.communicate = AsyncMock(return_value=(b"built", b""))

    deploy_proc = MagicMock()
    deploy_proc.returncode = 0
    deploy_proc.communicate = AsyncMock(
        return_value=(
            b"Uploaded files\nhttps://demo-project.pages.dev\nDeployment alias URL: https://preview-demo.wai-site-demo.pages.dev\n",
            b"",
        )
    )

    async def fake_shell(command, **kwargs):
        if command == "npm run build":
            (Path(kwargs["cwd"]) / "dist").mkdir(parents=True, exist_ok=True)
            (Path(kwargs["cwd"]) / "dist" / "index.html").write_text("ok", encoding="utf-8")
            return build_proc
        return install_proc

    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_shell",
            new=AsyncMock(side_effect=fake_shell),
        ) as mock_shell,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[create_proc, deploy_proc]),
        ) as mock_exec,
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_bundle_to_cloudflare_pages(
            "demo",
            {
                "package.json": '{"name":"demo"}',
                "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
                "src/main.tsx": "console.log('hi')",
            },
            branch="preview-demo",
            build_config={
                "install_command": "npm install --no-audit --no-fund",
                "command": "npm run build",
                "output_dir": "dist",
            },
        )

    assert result["success"] is True
    assert result["branch"] == "preview-demo"
    assert result["build_output_dir"] == "dist"
    assert result["build_command"] == "npm run build"
    shell_calls = [call.args[0] for call in mock_shell.await_args_list]
    assert shell_calls == ["npm install --no-audit --no-fund", "npm run build"]
    deploy_args = mock_exec.await_args_list[1].args
    assert deploy_args[:3] == ("wrangler", "pages", "deploy")


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_pages_surfaces_install_error():
    with patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings, patch(
        "app.services.agent.cloudflare_deploy._run_shell_command",
        new=AsyncMock(return_value={"returncode": 1, "stdout": "", "stderr": "npm failed"}),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_bundle_to_cloudflare_pages(
            "demo",
            {"package.json": '{"name":"demo"}', "index.html": "<!doctype html><html></html>"},
            build_config={
                "install_command": "npm install",
                "command": "npm run build",
                "output_dir": "dist",
            },
        )

    assert result == {"success": False, "error": "Install error: npm failed"}


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_pages_handles_build_output_missing():
    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy._run_shell_command",
            new=AsyncMock(
                side_effect=[
                    {"returncode": 0, "stdout": "", "stderr": ""},
                    {"returncode": 0, "stdout": "", "stderr": ""},
                ]
            ),
        ),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_bundle_to_cloudflare_pages(
            "demo",
            {"package.json": '{"name":"demo"}', "index.html": "<!doctype html><html></html>"},
            build_config={
                "install_command": "npm install",
                "command": "npm run build",
                "output_dir": "dist",
            },
        )

    assert result == {"success": False, "error": "Build output directory not found: dist"}


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_pages_surfaces_build_error():
    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy._run_shell_command",
            new=AsyncMock(
                side_effect=[
                    {"returncode": 0, "stdout": "", "stderr": ""},
                    {"returncode": 1, "stdout": "", "stderr": "build failed"},
                ]
            ),
        ),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_bundle_to_cloudflare_pages(
            "demo",
            {"package.json": '{"name":"demo"}', "index.html": "<!doctype html><html></html>"},
            build_config={
                "install_command": "npm install",
                "command": "npm run build",
                "output_dir": "dist",
            },
        )

    assert result == {"success": False, "error": "Build error: build failed"}


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_pages_handles_timeout_and_exception():
    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy._ensure_pages_project",
            new=AsyncMock(return_value={"success": True, "project_name": "wai-site-demo"}),
        ),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        with patch(
            "app.services.agent.cloudflare_deploy._run_pages_deploy",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            timeout_result = await deploy_bundle_to_cloudflare_pages(
                "demo",
                {"index.html": "<!doctype html><html></html>"},
            )

        with patch(
            "app.services.agent.cloudflare_deploy._run_pages_deploy",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            error_result = await deploy_bundle_to_cloudflare_pages(
                "demo",
                {"index.html": "<!doctype html><html></html>"},
            )

    assert timeout_result == {"success": False, "error": "Deploy timed out"}
    assert error_result == {"success": False, "error": "boom"}


@pytest.mark.asyncio
async def test_publish_bundle_to_cloudflare_pages_returns_live_url():
    with patch(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        new=AsyncMock(
            return_value={
                "success": True,
                "url": "https://wai-site-demo.pages.dev",
                "slug": "demo",
                "project_name": "wai-site-demo",
            }
        ),
    ) as mock_deploy:
        result = await publish_bundle_to_cloudflare_pages(
            "demo",
            {"index.html": "<!doctype html><html></html>"},
            project_name="wai-site-demo",
        )

    assert result["success"] is True
    assert result["url"] == "https://wai-site-demo.pages.dev"
    kwargs = mock_deploy.await_args.kwargs
    assert kwargs["branch"] is None
    assert kwargs["project_name"] == "wai-site-demo"


@pytest.mark.asyncio
async def test_deploy_to_cloudflare_pages_without_branch_returns_root_live_url():
    create_proc = MagicMock()
    create_proc.returncode = 0
    create_proc.communicate = AsyncMock(return_value=(b"created", b""))

    deploy_proc = MagicMock()
    deploy_proc.returncode = 0
    deploy_proc.communicate = AsyncMock(
        return_value=(b"Uploaded files\nhttps://abcd1234.wai-site-demo.pages.dev\n", b"")
    )

    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[create_proc, deploy_proc]),
        ),
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_to_cloudflare_pages(
            "demo",
            "<html></html>",
            project_name="wai-site-demo",
        )

    assert result["success"] is True
    assert result["url"] == "https://wai-site-demo.pages.dev"
    assert result["deployment_url"] == "https://abcd1234.wai-site-demo.pages.dev"


def test_project_name_helpers_are_stable():
    assert (
        project_name_for_slug("launch-site", kind="site", unique_key="abc123")
        == "wai-site-launch-site-abc123"
    )
    assert (
        live_url_for_project("wai-site-launch-site-abc123")
        == "https://wai-site-launch-site-abc123.pages.dev"
    )


@pytest.mark.asyncio
async def test_deploy_bundle_to_cloudflare_workers_runs_build_pipeline():
    async def fake_shell(command, **kwargs):
        if command == "npm run build":
            (Path(kwargs["cwd"]) / "dist").mkdir(parents=True, exist_ok=True)
            (Path(kwargs["cwd"]) / "dist" / "index.html").write_text("ok", encoding="utf-8")
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    worker_proc = MagicMock()
    worker_proc.returncode = 0
    worker_proc.communicate = AsyncMock(
        return_value=(b"Published\nhttps://wai-app-analytics-app123-preview.workers.dev\n", b"")
    )

    with (
        patch("app.services.agent.cloudflare_deploy.get_settings") as mock_settings,
        patch(
            "app.services.agent.cloudflare_deploy._run_shell_command",
            new=AsyncMock(side_effect=fake_shell),
        ) as mock_shell,
        patch(
            "app.services.agent.cloudflare_deploy.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=worker_proc),
        ) as mock_exec,
    ):
        mock_settings.return_value.cloudflare_api_token = "cf-token"
        mock_settings.return_value.cloudflare_account_id = "account-id"

        result = await deploy_bundle_to_cloudflare_workers(
            "analytics",
            {
                "package.json": '{"name":"analytics"}',
                "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
                "src/main.tsx": "console.log('hi')",
            },
            branch="preview-analytics",
            build_config={
                "install_command": "npm install --no-audit --no-fund",
                "command": "npm run build",
                "output_dir": "dist",
            },
            worker_name="wai-app-analytics-app123",
        )

    assert result["success"] is True
    assert result["deployment_url"] == "https://wai-app-analytics-app123-preview.workers.dev"
    assert result["alias_url"] == "https://wai-app-analytics-app123-preview.workers.dev"
    assert result["project_name"] == "wai-app-analytics-app123"
    assert result["branch"] == "preview-analytics"
    assert result["build_output_dir"] == "dist"
    assert result["build_command"] == "npm run build"
    shell_calls = [call.args[0] for call in mock_shell.await_args_list]
    assert shell_calls == ["npm install --no-audit --no-fund", "npm run build"]
    deploy_args = mock_exec.await_args.args
    assert deploy_args[:2] == ("wrangler", "deploy")


@pytest.mark.asyncio
async def test_publish_bundle_to_cloudflare_workers_returns_live_url():
    with patch(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_workers",
        new=AsyncMock(
            return_value={
                "success": True,
                "url": "https://wai-site-launch.workers.dev",
                "project_name": "wai-site-launch",
            }
        ),
    ) as mock_deploy:
        result = await publish_bundle_to_cloudflare_workers(
            "launch",
            {"index.html": "<!doctype html><html></html>"},
            worker_name="wai-site-launch",
        )

    assert result["success"] is True
    assert result["url"] == "https://wai-site-launch.workers.dev"
    kwargs = mock_deploy.await_args.kwargs
    assert kwargs["branch"] is None
    assert kwargs["worker_name"] == "wai-site-launch"


def test_worker_name_helpers_are_stable():
    assert (
        worker_name_for_slug("launch-site", kind="site", unique_key="abc123")
        == "wai-site-launch-site-abc123"
    )
    assert (
        preview_worker_name("wai-site-launch-site-abc123")
        == "wai-site-launch-site-abc123-preview"
    )
    assert (
        live_url_for_worker("wai-site-launch-site-abc123")
        == "https://wai-site-launch-site-abc123.workers.dev"
    )
