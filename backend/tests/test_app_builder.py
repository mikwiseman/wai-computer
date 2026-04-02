"""Tests for project bundle normalization in the app builder."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent import app_builder
from app.services.agent.app_builder import (
    _coerce_bundle,
    _generate_bundle,
    _generate_bundle_with_agent_sdk,
    _generate_slug,
    _get_bundle,
    _get_session_id,
    _preview_branch,
    _scaffold_bundle,
    _store_bundle,
    _store_session_id,
)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def ping(self):
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)


def make_builder_settings(**overrides):
    values = {
        "frontend_url": "https://wai.computer",
        "anthropic_api_key": "anthropic-key",
        "anthropic_model": "claude-test",
        "app_builder_generation_provider": "anthropic",
        "agent_sdk_model": "claude-sonnet-4-20250514",
        "agent_sdk_effort": "high",
        "agent_sdk_max_budget_usd": 1.0,
        "agent_sdk_max_turns": 10,
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def reset_redis_client(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", None)
    monkeypatch.setattr(app_builder, "_new_bundle_revision", lambda: "rev123")


def test_coerce_bundle_accepts_single_html():
    bundle = _coerce_bundle("<!doctype html><html><body>Hello</body></html>")

    assert bundle["kind"] == "single-html"
    assert bundle["framework"] == "html"
    assert bundle["files"]["index.html"].startswith("<!doctype html>")
    assert "build" not in bundle


def test_coerce_bundle_normalizes_project_build_config():
    bundle = _coerce_bundle(
        """
        {
          "kind": "vite-react-site",
          "framework": "react-vite",
          "files": {
            "package.json": "{\\"name\\": \\"demo\\"}",
            "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
            "src/main.tsx": "console.log('ready')"
          }
        }
        """
    )

    assert bundle["kind"] == "vite-react-site"
    assert bundle["framework"] == "react-vite"
    assert bundle["build"] == {
        "install_command": "npm install --no-audit --no-fund",
        "command": "npm run build",
        "output_dir": "dist",
    }


def test_coerce_bundle_rejects_unsafe_paths():
    with pytest.raises(ValueError, match="Unsafe bundle path"):
        _coerce_bundle(
            """
            {
              "files": {
                "../index.html": "<!doctype html><html></html>"
              }
            }
            """
        )


def test_generate_slug_transliterates_and_preview_branch_is_stable():
    assert _generate_slug("Привет Мир App") == "privet-mir-app"
    assert _generate_slug("Café launch") == "cafe-launch"
    assert _generate_slug("Hero, feature, CTA!") == "hero-feature-cta"
    assert _preview_branch("super-long-slug-name") == "preview-super-long-slug-name"


def test_scaffold_bundle_for_app_includes_api_client():
    bundle = _scaffold_bundle(
        mode="app",
        project_name="tracker",
        api_base_url="https://wai.computer",
        app_id="app-123",
    )

    assert bundle["kind"] == "vite-react-app"
    assert "src/lib/api.ts" in bundle["files"]
    assert "/api/apps/app-123" in bundle["files"]["src/lib/api.ts"]


def test_store_and_get_bundle_roundtrip(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(app_builder, "_redis_client", fake_redis)

    _store_bundle(
        "demo",
        {
            "kind": "vite-react-site",
            "framework": "react-vite",
            "files": {
                "package.json": '{"name":"demo"}',
                "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
                "src/main.tsx": "console.log('ready')",
            },
        },
    )

    bundle = _get_bundle("demo")
    assert bundle is not None
    assert bundle["kind"] == "vite-react-site"
    assert bundle["files"]["src/main.tsx"] == "console.log('ready')"


def test_coerce_bundle_handles_fenced_json_and_embedded_object():
    fenced = _coerce_bundle(
        """
        ```json
        {"files":{"index.html":"<!doctype html><html></html>"}}
        ```
        """
    )
    assert fenced["files"]["index.html"] == "<!doctype html><html></html>"

    embedded = _coerce_bundle(
        'Bundle follows:\n{"files":{"index.html":"<!doctype html><html></html>"}}\nThanks.'
    )
    assert embedded["files"]["index.html"] == "<!doctype html><html></html>"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "non-empty files object"),
        ({"files": {"index.html": 1}}, "must be a string"),
        ({"files": {"src/main.tsx": "console.log('x')"}}, "must include index.html"),
    ],
)
def test_normalize_bundle_validation_errors(payload, message):
    with pytest.raises(ValueError, match=message):
        app_builder._normalize_bundle(payload)


def test_get_redis_connects_and_handles_failure(monkeypatch):
    fake_redis = FakeRedis()
    fake_module = SimpleNamespace(from_url=lambda *args, **kwargs: fake_redis)
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )
    monkeypatch.setattr(app_builder, "_redis_client", None)
    monkeypatch.setitem(sys.modules, "redis", fake_module)

    assert app_builder._get_redis() is fake_redis

    def broken_from_url(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_builder, "_redis_client", None)
    monkeypatch.setitem(
        sys.modules,
        "redis",
        SimpleNamespace(from_url=broken_from_url),
    )
    assert app_builder._get_redis() is None


@pytest.mark.asyncio
async def test_build_app_generates_bundle_and_deploys(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(app_builder, "_redis_client", fake_redis)
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    response_text = """
    {
      "kind": "vite-react-app",
      "framework": "react-vite",
      "files": {
        "package.json": "{\\"name\\": \\"app\\"}",
        "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
        "src/main.tsx": "console.log('ready')",
        "src/lib/api.ts": "export const api = () => null;"
      }
    }
    """

    class FakeMessages:
        async def create(self, **kwargs):
            assert kwargs["model"] == "claude-test"
            assert "Build this app" in kwargs["messages"][0]["content"]
            return SimpleNamespace(content=[SimpleNamespace(text=response_text)])

    class FakeAnthropic:
        def __init__(self, api_key):
            assert api_key == "anthropic-key"
            self.messages = FakeMessages()

    async def fake_deploy(slug, files, *, branch=None, build_config=None, project_name=None):
        assert slug == "analytics-workspace"
        assert branch == "preview-analytics-workspace"
        assert project_name == "wai-app-analytics-workspace-app123"
        assert "package.json" in files
        assert build_config == {
            "install_command": "npm install --no-audit --no-fund",
            "command": "npm run build",
            "output_dir": "dist",
        }
        return {
            "success": True,
            "url": "https://preview-analytics-workspace.wai-app-analytics-workspace-app123.pages.dev",
            "branch": branch,
            "deployment_url": "https://deploy.pages.dev",
            "alias_url": "https://preview-analytics-workspace.wai-app-analytics-workspace-app123.pages.dev",
            "build_output_dir": "dist",
            "build_command": "npm run build",
        }

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        fake_deploy,
    )

    result = await app_builder.build_app("Analytics workspace", app_id="app-123", theme="sunrise")

    assert result["success"] is True
    assert result["bundle_kind"] == "vite-react-app"
    assert result["deployment_target"] == "cloudflare-pages"
    assert result["bundle_cache_key"] == "app-123:v:rev123"
    assert result["bundle_pointer_key"] == "app-123"
    assert result["project_name"] == "wai-app-analytics-workspace-app123"
    assert result["live_url"] == "https://wai-app-analytics-workspace-app123.pages.dev"
    stored = _get_bundle("app-123")
    assert stored is not None
    assert stored["framework"] == "react-vite"


@pytest.mark.asyncio
async def test_build_app_prefers_workers_when_available(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=(
                            '{"files":{"index.html":"<!doctype html>'
                            '<html><body>app</body></html>"}}'
                        )
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_workers_deploy(
        slug,
        files,
        *,
        branch=None,
        build_config=None,
        worker_name=None,
    ):
        assert slug == "ops-console"
        assert branch == "preview-ops-console"
        assert worker_name == "wai-app-ops-console-appops"
        return {
            "success": True,
            "url": "https://wai-app-ops-console-appops-preview.workers.dev",
            "project_name": "wai-app-ops-console-appops",
            "live_url": "https://wai-app-ops-console-appops.workers.dev",
            "branch": branch,
            "alias_url": "https://wai-app-ops-console-appops-preview.workers.dev",
            "deployment_url": "https://wai-app-ops-console-appops-preview.workers.dev",
            "deployment_target": "cloudflare-workers",
        }

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_workers",
        fake_workers_deploy,
    )

    result = await app_builder.build_app("Ops console", app_id="app-ops")

    assert result["success"] is True
    assert result["deployment_target"] == "cloudflare-workers"
    assert result["project_name"] == "wai-app-ops-console-appops"
    assert result["live_url"] == "https://wai-app-ops-console-appops.workers.dev"


@pytest.mark.asyncio
async def test_build_site_surfaces_deploy_failure(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(app_builder, "_redis_client", fake_redis)
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text="""
                        {
                          "kind": "vite-react-site",
                          "framework": "react-vite",
                          "files": {
                            "package.json": "{\\"name\\": \\"site\\"}",
                            "index.html": "<!doctype html><html></html>",
                            "src/main.tsx": "console.log('ready')"
                          }
                        }
                        """
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_deploy(slug, files, *, branch=None, build_config=None, project_name=None):
        return {"success": False, "error": "Build exploded"}

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        fake_deploy,
    )

    result = await app_builder.build_site("Conference website", theme="editorial")

    assert result["success"] is False
    assert result["error"] == "Build exploded"
    assert result["bundle_kind"] == "vite-react-site"


@pytest.mark.asyncio
async def test_build_app_surfaces_deploy_failure(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text='{"files":{"index.html":"<!doctype html><html></html>"}}'
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_deploy(slug, files, *, branch=None, build_config=None, project_name=None):
        return {"success": False, "error": "No deploy"}

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        fake_deploy,
    )

    result = await app_builder.build_app("Simple app", app_id="app-failure")

    assert result["success"] is False
    assert result["error"] == "No deploy"
    assert result["bundle_kind"] == "single-html"


@pytest.mark.asyncio
async def test_build_site_success_returns_metadata(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=(
                            '{"files":{"index.html":"<!doctype html><html><body>'
                            'site</body></html>"}}'
                        )
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_deploy(slug, files, *, branch=None, build_config=None, project_name=None):
        return {"success": True, "url": "https://preview-site.pages.dev", "branch": branch}

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        fake_deploy,
    )

    result = await app_builder.build_site("Maker showcase")

    assert result["success"] is True
    assert result["deployment_mode"] == "preview"
    assert result["bundle_kind"] == "single-html"
    assert result["bundle_cache_key"] == "site:maker-showcase:v:rev123"
    assert result["bundle_pointer_key"] == "site:maker-showcase"
    assert result["project_name"] == "wai-site-maker-showcase"


@pytest.mark.asyncio
async def test_build_site_uses_workers_for_complex_portal(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=(
                            '{"files":{"index.html":"<!doctype html>'
                            '<html><body>portal</body></html>"}}'
                        )
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_workers_deploy(
        slug,
        files,
        *,
        branch=None,
        build_config=None,
        worker_name=None,
    ):
        assert slug == "member-portal-with-login"
        assert worker_name == "wai-site-member-portal-with-login"
        return {
            "success": True,
            "url": "https://wai-site-member-portal-with-login-preview.workers.dev",
            "project_name": "wai-site-member-portal-with-login",
            "live_url": "https://wai-site-member-portal-with-login.workers.dev",
            "branch": branch,
            "deployment_url": "https://wai-site-member-portal-with-login-preview.workers.dev",
            "alias_url": "https://wai-site-member-portal-with-login-preview.workers.dev",
            "deployment_target": "cloudflare-workers",
        }

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_workers",
        fake_workers_deploy,
    )

    result = await app_builder.build_site("Member portal with login")

    assert result["success"] is True
    assert result["deployment_target"] == "cloudflare-workers"
    assert result["project_name"] == "wai-site-member-portal-with-login"


@pytest.mark.asyncio
async def test_edit_app_uses_cached_bundle(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(app_builder, "_redis_client", fake_redis)
    _store_bundle(
        "app-456",
        {
            "kind": "vite-react-site",
            "framework": "react-vite",
            "files": {
                "package.json": '{"name":"site"}',
                "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
                "src/main.tsx": "console.log('before')",
            },
        },
    )
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            assert "Current bundle" in kwargs["system"]
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text="""
                        {
                          "kind": "vite-react-site",
                          "framework": "react-vite",
                          "files": {
                            "package.json": "{\\"name\\": \\"site\\"}",
                            "index.html": "<!doctype html><html></html>",
                            "src/main.tsx": "console.log('after')"
                          }
                        }
                        """
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    async def fake_deploy(slug, files, *, branch=None, build_config=None, project_name=None):
        return {
            "success": True,
            "url": "https://preview-app-456.wai-sites.pages.dev",
            "branch": branch,
        }

    monkeypatch.setattr(app_builder.anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: False)
    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.deploy_bundle_to_cloudflare_pages",
        fake_deploy,
    )

    result = await app_builder.edit_app("app-456", "Polish the design")

    assert result["success"] is True
    assert result["bundle_kind"] == "vite-react-site"
    assert _get_bundle("app-456")["files"]["src/main.tsx"] == "console.log('after')"


@pytest.mark.asyncio
async def test_publish_cached_bundle_uses_live_deploy(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    _store_bundle(
        "site:launch",
        {
            "kind": "vite-react-site",
            "framework": "react-vite",
            "files": {
                "package.json": '{"name":"launch"}',
                "index.html": "<!doctype html><html><body><div id='root'></div></body></html>",
                "src/main.tsx": "console.log('launch')",
            },
        },
    )

    async def fake_publish(slug, files, *, project_name, build_config=None):
        assert slug == "launch"
        assert project_name == "wai-site-launch"
        assert build_config == {
            "install_command": "npm install --no-audit --no-fund",
            "command": "npm run build",
            "output_dir": "dist",
        }
        return {
            "success": True,
            "url": "https://wai-site-launch.pages.dev",
            "deployment_url": "https://deploy.pages.dev",
        }

    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.publish_bundle_to_cloudflare_pages",
        fake_publish,
    )

    result = await app_builder.publish_cached_bundle(
        "site:launch",
        project_name="wai-site-launch",
        slug="launch",
    )

    assert result["success"] is True
    assert result["deployment_mode"] == "production"
    assert result["url"] == "https://wai-site-launch.pages.dev"


@pytest.mark.asyncio
async def test_publish_cached_bundle_uses_workers_target(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    _store_bundle(
        "app:ops",
        {
            "kind": "single-html",
            "framework": "html",
            "files": {
                "index.html": "<!doctype html><html><body>ops</body></html>",
            },
        },
    )

    async def fake_publish(slug, files, *, worker_name, build_config=None):
        assert slug == "ops"
        assert worker_name == "wai-app-ops"
        assert build_config is None
        return {
            "success": True,
            "url": "https://wai-app-ops.workers.dev",
            "deployment_url": "https://wai-app-ops.workers.dev",
        }

    monkeypatch.setattr(
        "app.services.agent.cloudflare_deploy.publish_bundle_to_cloudflare_workers",
        fake_publish,
    )

    result = await app_builder.publish_cached_bundle(
        "app:ops",
        project_name="wai-app-ops",
        slug="ops",
        deployment_target="cloudflare-workers",
    )

    assert result["success"] is True
    assert result["deployment_mode"] == "production"
    assert result["deployment_target"] == "cloudflare-workers"
    assert result["url"] == "https://wai-app-ops.workers.dev"


@pytest.mark.asyncio
async def test_edit_app_returns_error_when_no_cached_bundle(monkeypatch):
    monkeypatch.setattr(app_builder, "_redis_client", FakeRedis())
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(),
    )

    result = await app_builder.edit_app("missing", "Do something")

    assert result == {"success": False, "error": "No stored bundle found for this app"}


def test_bundle_cache_helpers_swallow_redis_errors(monkeypatch):
    class BrokenRedis:
        def setex(self, key, ttl, value):
            raise RuntimeError("set failed")

        def get(self, key):
            raise RuntimeError("get failed")

    monkeypatch.setattr(app_builder, "_redis_client", BrokenRedis())

    _store_bundle("broken", {"files": {"index.html": "<!doctype html><html></html>"}})
    assert _get_bundle("broken") is None


@pytest.mark.asyncio
async def test_generate_bundle_prefers_agent_sdk_provider(monkeypatch):
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(app_builder_generation_provider="agent-sdk"),
    )
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: True)

    async def fake_agent_sdk(**kwargs):
        return {"files": {"index.html": "<!doctype html><html></html>"}}, "session-123"

    async def fake_anthropic(system_prompt, user_prompt):
        raise AssertionError("anthropic fallback should not run")

    monkeypatch.setattr(app_builder, "_generate_bundle_with_agent_sdk", fake_agent_sdk)
    monkeypatch.setattr(app_builder, "_generate_with_anthropic", fake_anthropic)

    bundle, provider, session_id = await _generate_bundle(
        mode="site",
        description="Marketing site",
        system_prompt="system",
        anthropic_user_prompt="user",
        scaffold_bundle={
            "kind": "vite-react-site",
            "files": {"index.html": "<!doctype html><html></html>"},
        },
    )

    assert provider == "agent-sdk"
    assert session_id == "session-123"
    assert bundle["files"]["index.html"] == "<!doctype html><html></html>"


@pytest.mark.asyncio
async def test_generate_bundle_falls_back_to_anthropic_when_agent_sdk_fails(monkeypatch):
    monkeypatch.setattr(
        app_builder,
        "get_settings",
        lambda: make_builder_settings(app_builder_generation_provider="auto"),
    )
    monkeypatch.setattr(app_builder, "_agent_sdk_available", lambda settings: True)

    async def broken_agent_sdk(**kwargs):
        raise RuntimeError("agent sdk broke")

    async def fake_anthropic(system_prompt, user_prompt):
        return '{"files":{"index.html":"<!doctype html><html></html>"}}'

    monkeypatch.setattr(app_builder, "_generate_bundle_with_agent_sdk", broken_agent_sdk)
    monkeypatch.setattr(app_builder, "_generate_with_anthropic", fake_anthropic)

    bundle, provider, session_id = await _generate_bundle(
        mode="site",
        description="Marketing site",
        system_prompt="system",
        anthropic_user_prompt="user",
        scaffold_bundle={
            "kind": "vite-react-site",
            "files": {"index.html": "<!doctype html><html></html>"},
        },
    )

    assert provider == "anthropic"
    assert session_id is None
    assert bundle["files"]["index.html"] == "<!doctype html><html></html>"


def test_session_id_store_and_get_roundtrip(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(app_builder, "_redis_client", fake_redis)

    _store_session_id("app-123", "sess-abc")
    assert _get_session_id("app-123") == "sess-abc"
    assert _get_session_id("missing") is None
