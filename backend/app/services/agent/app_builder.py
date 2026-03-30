"""App Builder — Lovable-level app and site generation.

Two modes:
- build_app(): Full interactive React app connected to Collections API
- build_site(): Static site / landing page

Generated apps are single HTML files with React 19 + Tailwind via CDN.
No build step — instant deploy to Cloudflare Pages.
"""

import logging
import re
import unicodedata

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
            result.append(ascii_char if ascii_char else "")

    slug = "".join(result).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")[:60]
    return slug or "app"


# ──────────────────────────────────────────────────────────────────────
# System prompt for app generation — the core of Lovable-level quality
# ──────────────────────────────────────────────────────────────────────

APP_SYSTEM_PROMPT = """You are an expert React developer building single-page applications.
Generate a COMPLETE, PRODUCTION-READY single HTML file that works as a standalone React app.

TECH STACK (all via CDN — NO build step):
- React 19 via: <script src="https://unpkg.com/react@19/umd/react.production.min.js"></script>
- ReactDOM 19 via: <script src="https://unpkg.com/react-dom@19/umd/react-dom.production.min.js"></script>
- Babel standalone: <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
- Tailwind CSS: <script src="https://cdn.tailwindcss.com"></script>
- Chart.js (if needed): <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>

API INTEGRATION:
The app connects to a backend API for data persistence.
Base URL: {api_base_url}
App ID: {app_id}

API endpoints:
- GET    /api/apps/{app_id}/items         → list all items
- POST   /api/apps/{app_id}/items         → create item (body: {{data: {{...}}}})
- PATCH  /api/apps/{app_id}/items/{{id}}  → update item (body: {{data: {{...}}}})
- DELETE /api/apps/{app_id}/items/{{id}}  → delete item

Auth: Use credentials: 'include' on all fetch calls (JWT cookie handles auth).

Data schema for this app:
{schema_json}

API CLIENT PATTERN (include in generated code):
```
const API = '{api_base_url}/api/apps/{app_id}';
async function api(path, opts = {{}}) {{
  const res = await fetch(API + path, {{
    ...opts,
    credentials: 'include',
    headers: {{ 'Content-Type': 'application/json', ...opts.headers }},
  }});
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}}
```

DESIGN SYSTEM:
- Font: Inter (via Google Fonts CDN)
- Spacing: 8px grid (p-2 = 8px, p-4 = 16px, p-6 = 24px)
- Border radius: rounded-xl for cards, rounded-lg for buttons/inputs
- Shadows: shadow-sm for cards, shadow-md on hover
- Colors: use a cohesive palette with CSS variables for easy theming
- Dark mode: support via Tailwind dark: prefix and prefers-color-scheme
- Responsive: mobile-first, works on 375px+

UI PATTERNS:
- Loading: skeleton placeholders while data loads
- Empty state: friendly message + call to action
- Error state: inline error with retry button
- Forms: labeled inputs, validation, submit with loading state
- Lists: clean cards with hover effects, swipe-to-delete on mobile (optional)
- Stats: summary cards at top, trends with Chart.js if numeric data
- Toasts: success/error notifications (position: fixed, auto-dismiss)
- Modals: for create/edit forms (with backdrop click to close)
- Search/filter: if list has >5 items, add a filter input

ANIMATION:
- Transitions: transition-all duration-200
- List items: fade-in on mount
- Buttons: scale-95 on active

CRITICAL RULES:
1. Output ONLY the complete HTML file. No explanation, no markdown.
2. The HTML must be valid and self-contained — no external files needed.
3. Include all React code in a single <script type="text/babel"> block.
4. Always start with data fetch on mount (useEffect).
5. Handle loading, error, and empty states.
6. Make it beautiful — this should look like a polished production app.
7. Include the <!DOCTYPE html>, <head> with meta viewport, and proper <title>.
"""

SITE_SYSTEM_PROMPT = """You are an expert web developer creating beautiful landing pages.
Generate a COMPLETE single HTML file — a polished, production-ready static website.

TECH STACK (all via CDN):
- Tailwind CSS: <script src="https://cdn.tailwindcss.com"></script>
- Alpine.js: <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js"></script>
- Google Fonts: Inter
- Lucide Icons: <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>

DESIGN SYSTEM:
- Spacing: py-24 for sections, py-16 for sub-sections, gap-8 for grids
- Typography: text-5xl md:text-6xl for h1, text-3xl md:text-4xl for h2
- Animations: IntersectionObserver fade-in (not Alpine transitions)
- Images: picsum.photos for placeholders with lazy loading
- Colors: cohesive palette via CSS variables
- Dark mode: support via prefers-color-scheme
- Responsive: mobile-first, 375px+

SECTIONS TO INCLUDE:
- Hero with headline + CTA
- Features/benefits grid
- Social proof / testimonials
- Pricing (if applicable)
- Footer with links

CRITICAL RULES:
1. Output ONLY the complete HTML file. No explanation, no markdown.
2. Content always visible by default (animations enhance, don't hide).
3. All text readable, high contrast, WCAG AA.
4. Beautiful — this should look like a $5000 landing page.
"""

EDIT_SYSTEM_PROMPT = """You are editing an existing web app/site. The user wants changes.
Here is the current HTML:

{current_html}

Apply the user's requested changes. Return the COMPLETE updated HTML file.
Preserve all existing functionality unless the user specifically asks to remove it.
Output ONLY the complete HTML file, no explanation."""


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

    prompt = APP_SYSTEM_PROMPT.format(
        api_base_url=api_base_url,
        app_id=app_id,
        schema_json=schema_json,
    )

    if theme:
        prompt += f"\n\nTheme preference: {theme}"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,  # Sonnet for code generation
        max_tokens=16384,
        system=prompt,
        messages=[
            {"role": "user", "content": f"Build this app: {description}"},
        ],
    )

    html = response.content[0].text.strip()
    # Strip markdown wrappers if present
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html[3:]
        html = html.rsplit("```", 1)[0] if "```" in html else html

    slug = _generate_slug(description[:60])
    _store_html(app_id, html)

    # Deploy
    from app.services.agent.cloudflare_deploy import deploy_to_cloudflare_pages

    deploy_result = await deploy_to_cloudflare_pages(slug, html)

    if deploy_result.get("success"):
        return {
            "success": True,
            "url": deploy_result["url"],
            "slug": slug,
            "app_id": app_id,
        }
    else:
        return {
            "success": False,
            "error": deploy_result.get("error", "Deploy failed"),
            "html_cached": True,
            "app_id": app_id,
        }


async def build_site(
    description: str,
    name: str | None = None,
    theme: str | None = None,
) -> dict:
    """Generate a static site/landing page and deploy it."""
    settings = get_settings()

    prompt = SITE_SYSTEM_PROMPT
    if theme:
        prompt += f"\n\nTheme: {theme}"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16384,
        system=prompt,
        messages=[
            {"role": "user", "content": f"Create this site: {description}"},
        ],
    )

    html = response.content[0].text.strip()
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html[3:]
        html = html.rsplit("```", 1)[0] if "```" in html else html

    slug = _generate_slug(name or description[:60])
    _store_html(f"site:{slug}", html)

    from app.services.agent.cloudflare_deploy import deploy_to_cloudflare_pages

    deploy_result = await deploy_to_cloudflare_pages(slug, html)

    if deploy_result.get("success"):
        return {"success": True, "url": deploy_result["url"], "slug": slug}
    else:
        return {
            "success": False,
            "error": deploy_result.get("error", "Deploy failed"),
            "html_cached": True,
        }


async def edit_app(app_id: str, instruction: str) -> dict:
    """Retrieve stored app HTML, apply edits via Claude, and redeploy."""
    settings = get_settings()
    current_html = _get_html(app_id)
    if not current_html:
        return {"success": False, "error": "No stored HTML found for this app"}

    prompt = EDIT_SYSTEM_PROMPT.format(current_html=current_html)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16384,
        system=prompt,
        messages=[
            {"role": "user", "content": instruction},
        ],
    )

    html = response.content[0].text.strip()
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html[3:]
        html = html.rsplit("```", 1)[0] if "```" in html else html

    _store_html(app_id, html)

    slug = _generate_slug(app_id)

    from app.services.agent.cloudflare_deploy import deploy_to_cloudflare_pages

    deploy_result = await deploy_to_cloudflare_pages(slug, html)

    if deploy_result.get("success"):
        return {"success": True, "url": deploy_result["url"], "slug": slug}
    else:
        return {"success": False, "error": deploy_result.get("error", "Deploy failed")}


def _store_html(key: str, html: str) -> None:
    """Cache generated HTML in Redis (TTL: 30 days)."""
    r = _get_redis()
    if r:
        try:
            r.setex(f"wai:app_html:{key}", 30 * 86400, html)
        except Exception as e:
            logger.debug(f"Redis store failed: {e}")


def _get_html(key: str) -> str | None:
    """Retrieve cached HTML from Redis."""
    r = _get_redis()
    if r:
        try:
            return r.get(f"wai:app_html:{key}")
        except Exception as e:
            logger.debug(f"Redis get failed: {e}")
    return None
