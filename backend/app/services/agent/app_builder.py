"""App Builder — project-based app and site generation.

Two modes:
- build_app(): Interactive data app connected to the Collections API
- build_site(): Marketing or content-heavy website

Generated artifacts are stored as deployable bundles. The preferred output is a
small Vite project so we can ship multi-file sites with a real build step, but
the builder still accepts single-file HTML as a fallback for fast/simple cases.
"""

import json
import logging
import re
import tempfile
import unicodedata
import uuid
from pathlib import Path, PurePosixPath

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)

# Redis is optional — used for caching generated HTML for edit flow
_redis_client = None


def _get_redis():
    """Lazy Redis connection — returns None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib

        settings = get_settings()
        if settings.redis_url:
            _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
            return _redis_client
    except Exception:
        _redis_client = False  # type: ignore[assignment]
    return None


def _generate_slug(name: str) -> str:
    """Generate a URL-safe slug from a name (supports Cyrillic)."""
    # Transliterate Cyrillic
    cyrillic_map = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    result = []
    for char in name.lower():
        if char in cyrillic_map:
            result.append(cyrillic_map[char])
        elif char.isascii() and (char.isalnum() or char in "-_ "):
            result.append(char)
        else:
            decomposed = unicodedata.normalize("NFD", char)
            ascii_char = decomposed.encode("ascii", "ignore").decode()
            clean_ascii = re.sub(r"[^A-Za-z0-9 _-]+", "", ascii_char)
            result.append(clean_ascii if clean_ascii else "")

    slug = "".join(result).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")[:60]
    return slug or "app"


def _preview_branch(slug: str) -> str:
    """Create a stable Cloudflare preview branch name for a generated artifact."""
    return f"preview-{slug}"[:63].strip("-")


def _new_bundle_revision() -> str:
    """Generate a short revision id for bundle history."""
    return uuid.uuid4().hex[:10]


def _versioned_bundle_cache_key(base_key: str) -> str:
    """Create a versioned bundle cache key while keeping a stable pointer key."""
    return f"{base_key}:v:{_new_bundle_revision()}"


# ──────────────────────────────────────────────────────────────────────
# System prompt for app generation — the core of Lovable-level quality
# ──────────────────────────────────────────────────────────────────────

APP_SYSTEM_PROMPT = """You are an expert product engineer building deployable web apps.
Generate a COMPLETE project bundle for a production-ready app.

RETURN FORMAT:
- Output ONLY valid JSON.
- No markdown fences, no commentary, no prose.
- Schema:
{
  "kind": "vite-react-app",
  "framework": "react-vite",
  "entry": "index.html",
  "build": {
    "install_command": "npm install --no-audit --no-fund",
    "command": "npm run build",
    "output_dir": "dist"
  },
  "files": {
    "package.json": "...",
    "tsconfig.json": "...",
    "vite.config.ts": "...",
    "index.html": "...",
    "src/main.tsx": "...",
    "src/App.tsx": "...",
    "src/styles.css": "...",
    "src/lib/api.ts": "..."
  },
  "metadata": {
    "summary": "short builder summary"
  }
}

TARGET STACK:
- Vite + React 19 + TypeScript
- Modern CSS in plain .css files with CSS variables
- Minimal dependencies: prefer only react, react-dom, vite, typescript, @vitejs/plugin-react
- No Tailwind, no Next.js, no server runtime
- Must build with `npm run build`

API INTEGRATION:
- Base URL: __API_BASE_URL__
- App ID: __APP_ID__
- Auth: credentials include
- Endpoints:
  - GET    /api/apps/__APP_ID__/items
  - POST   /api/apps/__APP_ID__/items
  - PATCH  /api/apps/__APP_ID__/{id}
  - DELETE /api/apps/__APP_ID__/{id}

DATA SCHEMA:
__SCHEMA_JSON__

REQUIREMENTS:
- Start with a real dashboard shell, not a toy form
- Support loading, error, empty, and success states
- Support create, edit, and delete flows
- Use responsive layout and polished spacing
- Use a visually distinctive but professional design
- Keep the bundle compact and coherent
- Include a title and metadata in index.html
"""

SITE_SYSTEM_PROMPT = """You are an expert web developer creating polished deployable websites.
Generate a COMPLETE project bundle for a production-ready static site.

RETURN FORMAT:
- Output ONLY valid JSON.
- No markdown fences, no commentary, no prose.
- Schema:
{
  "kind": "vite-react-site",
  "framework": "react-vite",
  "entry": "index.html",
  "build": {
    "install_command": "npm install --no-audit --no-fund",
    "command": "npm run build",
    "output_dir": "dist"
  },
  "files": {
    "package.json": "...",
    "tsconfig.json": "...",
    "vite.config.ts": "...",
    "index.html": "...",
    "src/main.tsx": "...",
    "src/App.tsx": "...",
    "src/styles.css": "..."
  },
  "metadata": {
    "summary": "short builder summary"
  }
}

TARGET STACK:
- Vite + React 19 + TypeScript
- Modern CSS in plain .css files with CSS variables
- Minimal dependencies only
- No server runtime
- Must build with `npm run build`

SITE REQUIREMENTS:
- Strong hero section
- Clear information architecture
- At least 4 meaningful sections
- Distinct visual identity, not generic SaaS template
- Responsive and accessible
- Include strong CTA and footer
"""

EDIT_SYSTEM_PROMPT = """You are editing an existing deployable web bundle.
Return ONLY valid JSON using the same bundle schema.

Current bundle:
{current_bundle_json}

Apply the user's requested changes.
Preserve existing functionality unless the user explicitly asks to remove it.
"""

_FILE_CACHE_PREFIX = "wai:app_bundle:"
_SESSION_CACHE_PREFIX = "wai:agent_session:"
_IGNORED_BUNDLE_PATH_PARTS = {"node_modules", "dist", ".git", ".claude", "__pycache__"}
_IGNORED_BUNDLE_FILENAMES = {".DS_Store"}
_COMPLEX_SITE_KEYWORDS = {
    "account",
    "admin",
    "api",
    "auth",
    "booking",
    "checkout",
    "cms",
    "crm",
    "dashboard",
    "data",
    "database",
    "editor",
    "form",
    "login",
    "member",
    "payment",
    "portal",
    "pricing calculator",
    "realtime",
    "search",
    "upload",
}


def _strip_wrappers(content: str) -> str:
    """Strip markdown wrappers from model output if present."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text, count=1)
        text = re.sub(r"\n?```$", "", text, count=1)
    return text.strip()


def _normalize_bundle_path(path: str) -> str:
    raw_path = str(path).strip().replace("\\", "/")
    candidate = PurePosixPath(raw_path)
    if (
        not raw_path
        or candidate.is_absolute()
        or raw_path.endswith("/")
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"Unsafe bundle path: {path!r}")
    return str(candidate)


def _html_bundle(html: str, *, kind: str = "single-html") -> dict:
    return {
        "kind": kind,
        "framework": "html",
        "entry": "index.html",
        "files": {"index.html": html},
        "metadata": {"summary": "Single-file HTML fallback bundle"},
    }


def _vite_package_json(name: str) -> str:
    return json.dumps(
        {
            "name": name,
            "private": True,
            "version": "0.0.1",
            "type": "module",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview --host 0.0.0.0 --port 4173",
            },
            "dependencies": {
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
            },
            "devDependencies": {
                "@types/react": "^19.0.0",
                "@types/react-dom": "^19.0.0",
                "@vitejs/plugin-react": "^5.0.0",
                "typescript": "^5.7.0",
                "vite": "^7.0.0",
            },
        },
        indent=2,
    )


def _scaffold_bundle(
    *,
    mode: str,
    project_name: str,
    api_base_url: str,
    app_id: str | None = None,
) -> dict:
    common_files = {
        "package.json": _vite_package_json(project_name),
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2020",
                    "useDefineForClassFields": True,
                    "lib": ["DOM", "DOM.Iterable", "ES2020"],
                    "allowJs": False,
                    "skipLibCheck": True,
                    "esModuleInterop": True,
                    "allowSyntheticDefaultImports": True,
                    "strict": True,
                    "forceConsistentCasingInFileNames": True,
                    "module": "ESNext",
                    "moduleResolution": "Node",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "noEmit": True,
                    "jsx": "react-jsx",
                },
                "include": ["src"],
            },
            indent=2,
        ),
        "vite.config.ts": (
            "import { defineConfig } from 'vite';\n"
            "import react from '@vitejs/plugin-react';\n\n"
            "export default defineConfig({\n"
            "  plugins: [react()],\n"
            "  server: { host: '0.0.0.0', port: 4173 },\n"
            "  preview: { host: '0.0.0.0', port: 4173 },\n"
            "});\n"
        ),
        "index.html": (
            "<!doctype html>\n"
            "<html lang=\"en\">\n"
            "  <head>\n"
            "    <meta charset=\"UTF-8\" />\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
            f"    <title>{project_name}</title>\n"
            "    <meta name=\"description\" content=\"Generated by Wai.\" />\n"
            "  </head>\n"
            "  <body>\n"
            "    <div id=\"root\"></div>\n"
            "    <script type=\"module\" src=\"/src/main.tsx\"></script>\n"
            "  </body>\n"
            "</html>\n"
        ),
        "src/main.tsx": (
            "import React from 'react';\n"
            "import ReactDOM from 'react-dom/client';\n"
            "import App from './App';\n"
            "import './styles.css';\n\n"
            "ReactDOM.createRoot(document.getElementById('root')!).render(\n"
            "  <React.StrictMode>\n"
            "    <App />\n"
            "  </React.StrictMode>,\n"
            ");\n"
        ),
        "src/styles.css": (
            ":root {\n"
            "  color-scheme: light dark;\n"
            "  --bg: #f6f4ee;\n"
            "  --surface: rgba(255, 255, 255, 0.75);\n"
            "  --text: #1d1a16;\n"
            "  --muted: #625b50;\n"
            "  --accent: #155dfc;\n"
            "}\n\n"
            "* { box-sizing: border-box; }\n"
            "body {\n"
            "  margin: 0;\n"
            "  min-height: 100vh;\n"
            "  font-family: Inter, ui-sans-serif, system-ui, sans-serif;\n"
            "  background: radial-gradient(circle at top, #fffef6 0%, var(--bg) 52%, #e2dfd2 100%);\n"
            "  color: var(--text);\n"
            "}\n\n"
            "button, input, textarea, select { font: inherit; }\n"
            "#root { min-height: 100vh; }\n"
        ),
    }

    if mode == "app":
        common_files["src/App.tsx"] = (
            "export default function App() {\n"
            "  return (\n"
            "    <main style={{ padding: 32 }}>\n"
            "      <h1>Generated Wai App</h1>\n"
            "      <p>Transform this scaffold into a polished data app.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )
        common_files["src/lib/api.ts"] = (
            f"const API_ROOT = '{api_base_url.rstrip('/')}/api/apps/{app_id}';\n\n"
            "export async function api(path: string, options: RequestInit = {}) {\n"
            "  const response = await fetch(`${API_ROOT}${path}`, {\n"
            "    ...options,\n"
            "    credentials: 'include',\n"
            "    headers: {\n"
            "      'Content-Type': 'application/json',\n"
            "      ...(options.headers ?? {}),\n"
            "    },\n"
            "  });\n"
            "  if (!response.ok) {\n"
            "    throw new Error(await response.text());\n"
            "  }\n"
            "  return response.json();\n"
            "}\n"
        )
        kind = "vite-react-app"
    else:
        common_files["src/App.tsx"] = (
            "export default function App() {\n"
            "  return (\n"
            "    <main style={{ padding: 32 }}>\n"
            "      <h1>Generated Wai Site</h1>\n"
            "      <p>Transform this scaffold into a polished marketing site.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )
        kind = "vite-react-site"

    return _normalize_bundle(
        {
            "kind": kind,
            "framework": "react-vite",
            "entry": "index.html",
            "files": common_files,
        }
    )


def _collect_bundle_from_directory(root: Path, *, kind: str) -> dict:
    files: dict[str, str] = {}
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name in _IGNORED_BUNDLE_FILENAMES:
            continue
        relative = file_path.relative_to(root)
        if any(part in _IGNORED_BUNDLE_PATH_PARTS for part in relative.parts):
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.debug("Skipping non-text bundle file %s", relative)
            continue
        files[str(relative.as_posix())] = content

    return _normalize_bundle(
        {
            "kind": kind,
            "framework": "react-vite" if "package.json" in files else "html",
            "entry": "index.html",
            "files": files,
        }
    )


def _write_bundle_to_directory(root: Path, bundle: dict) -> None:
    for relative_path, content in bundle["files"].items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _builder_provider(settings) -> str:
    provider = settings.app_builder_generation_provider.strip().lower()
    if provider in {"agent-sdk", "agent_sdk"}:
        return "agent-sdk"
    if provider in {"anthropic", "raw-anthropic"}:
        return "anthropic"
    return "auto"


def _normalize_deployment_target(target: str | None) -> str:
    normalized = (target or "").strip().lower()
    if normalized in {"workers", "cloudflare-workers", "worker"}:
        return "cloudflare-workers"
    if normalized in {"pages", "cloudflare-pages", "page"}:
        return "cloudflare-pages"
    return "auto"


def _description_prefers_workers(description: str) -> bool:
    lowered = description.lower()
    return any(keyword in lowered for keyword in _COMPLEX_SITE_KEYWORDS)


def _deployment_targets_for(
    *,
    mode: str,
    description: str,
    requested_target: str | None = None,
) -> list[str]:
    settings = get_settings()
    target = _normalize_deployment_target(
        requested_target or getattr(settings, "app_builder_default_deployment_target", "auto")
    )
    if target in {"cloudflare-pages", "cloudflare-workers"}:
        return [target]

    if mode == "app":
        return ["cloudflare-workers", "cloudflare-pages"]
    if _description_prefers_workers(description):
        return ["cloudflare-workers", "cloudflare-pages"]
    return ["cloudflare-pages"]


async def _deploy_generated_bundle(
    *,
    mode: str,
    description: str,
    slug: str,
    unique_key: str | None,
    files: dict[str, str],
    build_config: dict | None,
    requested_target: str | None = None,
) -> dict:
    from app.services.agent.cloudflare_deploy import (
        deploy_bundle_to_cloudflare_pages,
        deploy_bundle_to_cloudflare_workers,
        live_url_for_project,
        live_url_for_worker,
        project_name_for_slug,
        worker_name_for_slug,
    )

    attempted: list[str] = []
    last_result: dict | None = None
    for target in _deployment_targets_for(
        mode=mode,
        description=description,
        requested_target=requested_target,
    ):
        attempted.append(target)
        if target == "cloudflare-workers":
            resource_name = worker_name_for_slug(slug, kind=mode, unique_key=unique_key)
            deploy_result = await deploy_bundle_to_cloudflare_workers(
                slug,
                files,
                branch=_preview_branch(slug),
                build_config=build_config,
                worker_name=resource_name,
            )
            if deploy_result.get("success"):
                deploy_result.setdefault("project_name", resource_name)
                deploy_result.setdefault("live_url", live_url_for_worker(resource_name))
                deploy_result["deployment_target"] = "cloudflare-workers"
                return deploy_result
            last_result = deploy_result
            continue

        resource_name = project_name_for_slug(slug, kind=mode, unique_key=unique_key)
        deploy_result = await deploy_bundle_to_cloudflare_pages(
            slug,
            files,
            branch=_preview_branch(slug),
            build_config=build_config,
            project_name=resource_name,
        )
        if deploy_result.get("success"):
            deploy_result.setdefault("project_name", resource_name)
            deploy_result.setdefault("live_url", live_url_for_project(resource_name))
            deploy_result["deployment_target"] = "cloudflare-pages"
            return deploy_result
        last_result = deploy_result

    error = "Deploy failed"
    if last_result:
        error = last_result.get("error", error)
    return {
        "success": False,
        "error": error,
        "attempted_targets": attempted,
    }


def _agent_sdk_available(settings) -> bool:
    if not settings.anthropic_api_key:
        return False
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        return False


async def _generate_with_anthropic(system_prompt: str, user_prompt: str) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


async def _generate_bundle_with_agent_sdk(
    *,
    mode: str,
    description: str,
    system_prompt: str,
    scaffold_bundle: dict,
    instruction: str | None = None,
) -> tuple[dict, str | None]:
    """Generate a bundle using the Claude Agent SDK with full tool use.

    Returns (bundle_dict, session_id) where session_id can be used for edits.
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    settings = get_settings()

    task_description = instruction or description
    task_prompt = (
        "You have a Vite + React + TypeScript project scaffold in the current directory.\n"
        "Transform it into a production-ready "
        f"{'data app' if mode == 'app' else 'website'}.\n\n"
        f"Request: {task_description}\n\n"
        "Rules:\n"
        "- Edit files directly in the working tree using Write and Edit tools.\n"
        "- Keep the project buildable with `npm run build`.\n"
        "- Keep the project compact and polished.\n"
        "- When done, leave the updated source files on disk.\n"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        _write_bundle_to_directory(project_dir, scaffold_bundle)

        session_id = None
        async for message in query(
            prompt=task_prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
                disallowed_tools=["Bash", "WebSearch", "WebFetch", "Agent"],
                permission_mode="bypassPermissions",
                system_prompt=system_prompt,
                model=settings.agent_sdk_model,
                effort=settings.agent_sdk_effort,
                max_turns=settings.agent_sdk_max_turns,
                max_budget_usd=settings.agent_sdk_max_budget_usd,
                cwd=str(project_dir),
                env={"ANTHROPIC_API_KEY": settings.anthropic_api_key},
            ),
        ):
            if hasattr(message, "subtype") and message.subtype == "init":
                session_id = getattr(message, "session_id", None)
            if hasattr(message, "type") and message.type == "assistant":
                tool_name = getattr(message, "tool_name", None)
                if tool_name:
                    logger.info("Agent SDK tool call: %s", tool_name)

        logger.info(
            "Agent SDK bundle generation OK mode=%s session_id=%s",
            mode,
            session_id,
        )
        bundle = _collect_bundle_from_directory(
            project_dir, kind=scaffold_bundle["kind"]
        )
        return bundle, session_id


async def _generate_bundle(
    *,
    mode: str,
    description: str,
    system_prompt: str,
    anthropic_user_prompt: str,
    scaffold_bundle: dict,
    instruction: str | None = None,
) -> tuple[dict, str, str | None]:
    """Generate a bundle. Returns (bundle, provider_name, session_id)."""
    settings = get_settings()
    provider = _builder_provider(settings)

    if provider in {"agent-sdk", "auto"} and _agent_sdk_available(settings):
        try:
            bundle, session_id = await _generate_bundle_with_agent_sdk(
                mode=mode,
                description=description,
                system_prompt=system_prompt,
                scaffold_bundle=scaffold_bundle,
                instruction=instruction,
            )
            return _normalize_bundle(bundle), "agent-sdk", session_id
        except Exception as exc:
            logger.warning("Agent SDK generation failed, falling back to Anthropic: %s", exc)
            if provider == "agent-sdk":
                raise

    text = await _generate_with_anthropic(system_prompt, anthropic_user_prompt)
    return _coerce_bundle(text), "anthropic", None


def _normalize_bundle(bundle: dict) -> dict:
    if not isinstance(bundle, dict):
        raise ValueError("Bundle payload must be an object")

    raw_files = bundle.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("Bundle must contain a non-empty files object")

    files: dict[str, str] = {}
    for path, content in raw_files.items():
        normalized_path = _normalize_bundle_path(path)
        if not isinstance(content, str):
            raise ValueError(f"Bundle file {normalized_path!r} must be a string")
        files[normalized_path] = content

    if "index.html" not in files:
        raise ValueError("Bundle must include index.html")

    raw_build = bundle.get("build")
    build = raw_build if isinstance(raw_build, dict) else {}

    if "package.json" in files:
        build = {
            "install_command": build.get("install_command") or "npm install --no-audit --no-fund",
            "command": build.get("command") or "npm run build",
            "output_dir": build.get("output_dir") or "dist",
        }
    else:
        build = {}

    metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
    framework = bundle.get("framework") if isinstance(bundle.get("framework"), str) else "html"
    kind = bundle.get("kind") if isinstance(bundle.get("kind"), str) else (
        "bundle-project" if build else "single-html"
    )

    normalized = {
        "version": 1,
        "kind": kind,
        "framework": framework,
        "entry": bundle.get("entry") if isinstance(bundle.get("entry"), str) else "index.html",
        "files": files,
        "metadata": metadata,
    }
    if build:
        normalized["build"] = build
    return normalized


def _coerce_bundle(content: str) -> dict:
    """Convert model output into a normalized deployable bundle."""
    text = _strip_wrappers(content)
    if text.startswith("{"):
        return _normalize_bundle(json.loads(text))

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(text[start : end + 1])
        else:
            lower = text.lower()
            if lower.startswith("<!doctype html") or "<html" in lower:
                return _normalize_bundle(_html_bundle(text))
            raise ValueError("Model response was neither HTML nor JSON bundle")

    return _normalize_bundle(parsed)


async def build_app(
    description: str,
    app_id: str,
    schema: dict | None = None,
    theme: str | None = None,
) -> dict:
    """Generate a full interactive React app and deploy it."""
    settings = get_settings()
    api_base_url = settings.frontend_url.rstrip("/")

    schema_json = "No specific schema — infer from the description." if not schema else str(schema)

    prompt = (
        APP_SYSTEM_PROMPT.replace("__API_BASE_URL__", api_base_url)
        .replace("__APP_ID__", app_id)
        .replace("__SCHEMA_JSON__", schema_json)
    )

    if theme:
        prompt += f"\n\nTheme preference: {theme}"

    scaffold_bundle = _scaffold_bundle(
        mode="app",
        project_name=_generate_slug(description[:60]),
        api_base_url=api_base_url,
        app_id=app_id,
    )
    bundle, generation_provider, session_id = await _generate_bundle(
        mode="app",
        description=description,
        system_prompt=prompt,
        anthropic_user_prompt=f"Build this app: {description}",
        scaffold_bundle=scaffold_bundle,
    )

    slug = _generate_slug(description[:60])
    pointer_key = app_id
    cache_key = _versioned_bundle_cache_key(pointer_key)
    _store_bundle(pointer_key, bundle)
    _store_bundle(cache_key, bundle)
    if session_id:
        _store_session_id(pointer_key, session_id)

    deploy_result = await _deploy_generated_bundle(
        mode="app",
        description=description,
        slug=slug,
        unique_key=app_id,
        files=bundle["files"],
        build_config=bundle.get("build"),
        requested_target=bundle.get("metadata", {}).get("deployment_target"),
    )

    if deploy_result.get("success"):
        return {
            "success": True,
            "url": deploy_result["url"],
            "slug": slug,
            "app_id": app_id,
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "artifact_mode": "bundle",
            "generation_provider": generation_provider,
            "bundle_cache_key": cache_key,
            "bundle_pointer_key": pointer_key,
            "project_name": deploy_result.get("project_name"),
            "live_url": deploy_result.get("live_url"),
            "deployment_mode": "preview",
            "deployment_branch": deploy_result.get("branch"),
            "deployment_url": deploy_result.get("deployment_url"),
            "alias_url": deploy_result.get("alias_url"),
            "build_output_dir": deploy_result.get("build_output_dir"),
            "build_command": deploy_result.get("build_command"),
            "deployment_target": deploy_result.get("deployment_target", "cloudflare-pages"),
        }
    else:
        return {
            "success": False,
            "error": deploy_result.get("error", "Deploy failed"),
            "html_cached": "index.html" in bundle["files"],
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "generation_provider": generation_provider,
            "app_id": app_id,
        }


async def build_site(
    description: str,
    name: str | None = None,
    theme: str | None = None,
    site_key: str | None = None,
) -> dict:
    """Generate a static site/landing page and deploy it."""
    settings = get_settings()

    prompt = SITE_SYSTEM_PROMPT
    if theme:
        prompt += f"\n\nTheme: {theme}"

    scaffold_bundle = _scaffold_bundle(
        mode="site",
        project_name=_generate_slug(name or description[:60]),
        api_base_url=settings.frontend_url.rstrip("/"),
    )
    bundle, generation_provider, session_id = await _generate_bundle(
        mode="site",
        description=description,
        system_prompt=prompt,
        anthropic_user_prompt=f"Create this site: {description}",
        scaffold_bundle=scaffold_bundle,
    )

    slug = _generate_slug(name or description[:60])
    pointer_key = f"site:{site_key or slug}"
    cache_key = _versioned_bundle_cache_key(pointer_key)
    _store_bundle(pointer_key, bundle)
    _store_bundle(cache_key, bundle)
    if session_id:
        _store_session_id(pointer_key, session_id)

    deploy_result = await _deploy_generated_bundle(
        mode="site",
        description=description,
        slug=slug,
        unique_key=site_key,
        files=bundle["files"],
        build_config=bundle.get("build"),
        requested_target=bundle.get("metadata", {}).get("deployment_target"),
    )

    if deploy_result.get("success"):
        return {
            "success": True,
            "url": deploy_result["url"],
            "slug": slug,
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "artifact_mode": "bundle",
            "generation_provider": generation_provider,
            "bundle_cache_key": cache_key,
            "bundle_pointer_key": pointer_key,
            "project_name": deploy_result.get("project_name"),
            "live_url": deploy_result.get("live_url"),
            "site_key": site_key,
            "deployment_mode": "preview",
            "deployment_branch": deploy_result.get("branch"),
            "deployment_url": deploy_result.get("deployment_url"),
            "alias_url": deploy_result.get("alias_url"),
            "build_output_dir": deploy_result.get("build_output_dir"),
            "build_command": deploy_result.get("build_command"),
            "deployment_target": deploy_result.get("deployment_target", "cloudflare-pages"),
        }
    else:
        return {
            "success": False,
            "error": deploy_result.get("error", "Deploy failed"),
            "html_cached": "index.html" in bundle["files"],
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "generation_provider": generation_provider,
        }


async def edit_app(app_id: str, instruction: str) -> dict:
    """Retrieve stored app HTML, apply edits via Claude, and redeploy."""
    current_bundle = _get_bundle(app_id)
    if current_bundle is None:
        return {"success": False, "error": "No stored bundle found for this app"}

    prompt = EDIT_SYSTEM_PROMPT.format(
        current_bundle_json=json.dumps(current_bundle, ensure_ascii=False, indent=2)
    )

    bundle, generation_provider, session_id = await _generate_bundle(
        mode="app" if current_bundle["kind"] == "vite-react-app" else "site",
        description=app_id,
        system_prompt=prompt,
        anthropic_user_prompt=instruction,
        scaffold_bundle=current_bundle,
        instruction=instruction,
    )

    _store_bundle(app_id, bundle)
    if session_id:
        _store_session_id(app_id, session_id)
    cache_key = _versioned_bundle_cache_key(app_id)
    _store_bundle(cache_key, bundle)

    slug = _generate_slug(app_id)

    deploy_result = await _deploy_generated_bundle(
        mode="app" if current_bundle["kind"] == "vite-react-app" else "site",
        description=instruction,
        slug=slug,
        unique_key=app_id,
        files=bundle["files"],
        build_config=bundle.get("build"),
        requested_target=current_bundle.get("metadata", {}).get("deployment_target"),
    )

    if deploy_result.get("success"):
        return {
            "success": True,
            "url": deploy_result["url"],
            "slug": slug,
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "artifact_mode": "bundle",
            "generation_provider": generation_provider,
            "bundle_cache_key": cache_key,
            "bundle_pointer_key": app_id,
            "project_name": deploy_result.get("project_name"),
            "live_url": deploy_result.get("live_url"),
            "deployment_mode": "preview",
            "deployment_branch": deploy_result.get("branch"),
            "deployment_url": deploy_result.get("deployment_url"),
            "alias_url": deploy_result.get("alias_url"),
            "build_output_dir": deploy_result.get("build_output_dir"),
            "build_command": deploy_result.get("build_command"),
            "deployment_target": deploy_result.get("deployment_target", "cloudflare-pages"),
        }
    else:
        return {"success": False, "error": deploy_result.get("error", "Deploy failed")}


async def publish_cached_bundle(
    cache_key: str,
    *,
    project_name: str,
    slug: str,
    deployment_target: str = "cloudflare-pages",
) -> dict:
    """Promote a cached bundle to the live Pages URL for its project."""
    bundle = _get_bundle(cache_key)
    if bundle is None:
        return {"success": False, "error": "No stored bundle found for this app"}

    normalized_target = _normalize_deployment_target(deployment_target)
    if normalized_target == "cloudflare-workers":
        from app.services.agent.cloudflare_deploy import (
            live_url_for_worker,
            publish_bundle_to_cloudflare_workers,
        )

        deploy_result = await publish_bundle_to_cloudflare_workers(
            slug,
            bundle["files"],
            worker_name=project_name,
            build_config=bundle.get("build"),
        )
        live_url = live_url_for_worker(project_name)
        deployment_target_value = "cloudflare-workers"
    else:
        from app.services.agent.cloudflare_deploy import (
            live_url_for_project,
            publish_bundle_to_cloudflare_pages,
        )

        deploy_result = await publish_bundle_to_cloudflare_pages(
            slug,
            bundle["files"],
            project_name=project_name,
            build_config=bundle.get("build"),
        )
        live_url = live_url_for_project(project_name)
        deployment_target_value = "cloudflare-pages"

    if deploy_result.get("success"):
        return {
            "success": True,
            "url": deploy_result["url"],
            "slug": slug,
            "project_name": project_name,
            "bundle_kind": bundle["kind"],
            "framework": bundle["framework"],
            "artifact_mode": "bundle",
            "bundle_cache_key": cache_key,
            "deployment_mode": "production",
            "deployment_url": deploy_result.get("deployment_url"),
            "alias_url": deploy_result.get("alias_url"),
            "live_url": deploy_result.get("live_url", live_url),
            "build_output_dir": deploy_result.get("build_output_dir"),
            "build_command": deploy_result.get("build_command"),
            "deployment_target": deployment_target_value,
        }
    return {"success": False, "error": deploy_result.get("error", "Deploy failed")}

def _store_bundle(key: str, bundle: dict) -> None:
    """Cache generated bundle in Redis (TTL: 30 days)."""
    r = _get_redis()
    if r:
        try:
            r.setex(f"{_FILE_CACHE_PREFIX}{key}", 30 * 86400, json.dumps(bundle))
        except Exception as e:
            logger.debug(f"Redis bundle store failed: {e}")


def _get_bundle(key: str) -> dict | None:
    """Retrieve cached bundle from Redis."""
    r = _get_redis()
    if r:
        try:
            value = r.get(f"{_FILE_CACHE_PREFIX}{key}")
            if value:
                return _normalize_bundle(json.loads(value))
        except Exception as e:
            logger.debug(f"Redis bundle get failed: {e}")
    return None


def _store_session_id(key: str, session_id: str) -> None:
    """Cache Agent SDK session ID in Redis (TTL: 7 days)."""
    r = _get_redis()
    if r:
        try:
            r.setex(f"{_SESSION_CACHE_PREFIX}{key}", 7 * 86400, session_id)
        except Exception as e:
            logger.debug(f"Redis session store failed: {e}")


def _get_session_id(key: str) -> str | None:
    """Retrieve cached Agent SDK session ID from Redis."""
    r = _get_redis()
    if r:
        try:
            return r.get(f"{_SESSION_CACHE_PREFIX}{key}")
        except Exception as e:
            logger.debug(f"Redis session get failed: {e}")
    return None
