"""The data-source catalog — single source of truth for the Hermes-style
"connect a source" surface on web / Mac / iOS.

Served by ``GET /api/source-catalog`` so we can add providers, fix URLs, or flip
a ``coming_soon`` entry to ``available`` **without shipping a client release**.
Clients render the categorized toggle list from this payload and connect by
``catalog_id`` (the server resolves ``server_url`` / ``auth_type`` from here, so a
client can't point a "Gmail" tile at an arbitrary URL).

Honesty rule (no fake toggles): an entry is ``available`` only when its connect
path genuinely works today. OAuth-remote providers stay ``coming_soon`` until the
OAuth client flow ships; local-only (Obsidian) and bridge-only (Gmail/Drive)
providers stay ``coming_soon`` until their connectors ship. The always-working
path is **Add custom MCP** (paste an HTTPS URL + optional token), which the
client renders from ``custom_supported`` below — any server matching a recipe
(Telegram/Notion/Gmail/Obsidian/WaiTime/WaiMoney) gets a great plan immediately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

CATALOG_VERSION = 1


@dataclass(frozen=True)
class CatalogCategory:
    id: str
    name_en: str
    name_ru: str


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    category: str
    icon: str                      # slug -> client maps to a brand/category glyph
    tagline_en: str
    tagline_ru: str
    syncs_en: str
    syncs_ru: str
    auth_type: str                 # none | pat | oauth
    server_url: str                # resolved server-side; never trusted from client
    transport: str = "streamable_http"
    default_sync_interval_minutes: int = 60
    setup_hint_en: str | None = None
    setup_hint_ru: str | None = None
    status: str = "coming_soon"    # available | coming_soon


CATEGORIES: list[CatalogCategory] = [
    CatalogCategory("communication", "Communication", "Общение"),
    CatalogCategory("notes", "Notes & docs", "Заметки и документы"),
    CatalogCategory("files", "Files & storage", "Файлы и хранилище"),
    CatalogCategory("calendar", "Calendars", "Календари"),
    CatalogCategory("productivity", "Productivity", "Продуктивность"),
]


# NOTE: OAuth-remote + bridge + local providers are coming_soon until those
# connectors ship (the OAuth client flow + first-party bridges are later phases).
# Flip to "available" here — no client release needed — when the path works.
ENTRIES: list[CatalogEntry] = [
    CatalogEntry(
        id="gmail", name="Gmail", category="communication", icon="gmail",
        tagline_en="Pull important threads into your brain.",
        tagline_ru="Подтягивайте важные переписки в свою базу.",
        syncs_en="Threads, messages, and attachments (read-only).",
        syncs_ru="Цепочки, письма и вложения (только чтение).",
        auth_type="oauth", server_url="https://wai.computer/mcp/bridge/gmail",
        default_sync_interval_minutes=60, status="coming_soon",
    ),
    CatalogEntry(
        id="telegram", name="Telegram", category="communication", icon="telegram",
        tagline_en="Save the chats and channels you care about.",
        tagline_ru="Сохраняйте нужные чаты и каналы.",
        syncs_en="Selected chats and channels (read-only).",
        syncs_ru="Выбранные чаты и каналы (только чтение).",
        auth_type="pat", server_url="https://wai.computer/mcp/bridge/telegram",
        default_sync_interval_minutes=30, status="coming_soon",
        setup_hint_en="Paste your WaiTelegram access token.",
        setup_hint_ru="Вставьте токен доступа WaiTelegram.",
    ),
    CatalogEntry(
        id="slack", name="Slack", category="communication", icon="slack",
        tagline_en="Index channels and threads you follow.",
        tagline_ru="Индексируйте каналы и треды, которые вы читаете.",
        syncs_en="Channels, threads, and files (read-only).",
        syncs_ru="Каналы, треды и файлы (только чтение).",
        auth_type="oauth", server_url="https://wai.computer/mcp/bridge/slack",
        status="coming_soon",
    ),
    CatalogEntry(
        id="notion", name="Notion", category="notes", icon="notion",
        tagline_en="Index your workspace pages and databases.",
        tagline_ru="Индексируйте страницы и базы воркспейса.",
        syncs_en="Pages and databases (read-only).",
        syncs_ru="Страницы и базы (только чтение).",
        auth_type="oauth", server_url="https://mcp.notion.com/mcp",
        default_sync_interval_minutes=120, status="coming_soon",
    ),
    CatalogEntry(
        id="obsidian", name="Obsidian", category="notes", icon="obsidian",
        tagline_en="Bring your vault notes and links in.",
        tagline_ru="Подтяните заметки и связи из вашего хранилища.",
        syncs_en="Vault notes, tags, and [[wikilinks]] (read-only).",
        syncs_ru="Заметки, теги и [[вики-ссылки]] (только чтение).",
        auth_type="pat", server_url="https://wai.computer/mcp/bridge/obsidian",
        default_sync_interval_minutes=120, status="coming_soon",
        setup_hint_en="Obsidian is local-only — desktop bridge coming soon.",
        setup_hint_ru="Obsidian работает локально — мост для десктопа скоро.",
    ),
    CatalogEntry(
        id="google_drive", name="Google Drive", category="files", icon="google_drive",
        tagline_en="Index your docs, sheets, and PDFs.",
        tagline_ru="Индексируйте документы, таблицы и PDF.",
        syncs_en="Documents, sheets, and PDFs (read-only).",
        syncs_ru="Документы, таблицы и PDF (только чтение).",
        auth_type="oauth", server_url="https://wai.computer/mcp/bridge/google-drive",
        default_sync_interval_minutes=120, status="coming_soon",
    ),
    CatalogEntry(
        id="google_calendar", name="Google Calendar", category="calendar", icon="google_calendar",
        tagline_en="Keep your meetings and invitees in your brain.",
        tagline_ru="Держите встречи и участников в своей базе.",
        syncs_en="Events and attendees (read-only).",
        syncs_ru="События и участники (только чтение).",
        auth_type="oauth", server_url="https://wai.computer/mcp/bridge/google-calendar",
        status="coming_soon",
    ),
    CatalogEntry(
        id="wai_time", name="WaiTime", category="productivity", icon="wai_time",
        tagline_en="Bring your time entries and projects in.",
        tagline_ru="Подтяните записи времени и проекты.",
        syncs_en="Time entries, projects, and tags (read-only).",
        syncs_ru="Записи времени, проекты и теги (только чтение).",
        auth_type="pat", server_url="https://wai.computer/mcp/bridge/wai-time",
        status="coming_soon",
        setup_hint_en="Paste your WaiTime API token.",
        setup_hint_ru="Вставьте API-токен WaiTime.",
    ),
    CatalogEntry(
        id="wai_money", name="WaiMoney", category="productivity", icon="wai_money",
        tagline_en="Bring your transactions and budgets in.",
        tagline_ru="Подтяните транзакции и бюджеты.",
        syncs_en="Transactions and budgets (read-only).",
        syncs_ru="Транзакции и бюджеты (только чтение).",
        auth_type="pat", server_url="https://wai.computer/mcp/bridge/wai-money",
        status="coming_soon",
        setup_hint_en="Paste your WaiMoney API token.",
        setup_hint_ru="Вставьте API-токен WaiMoney.",
    ),
]

_BY_ID = {e.id: e for e in ENTRIES}

# Whether the "Add custom MCP (advanced)" path is offered (paste any HTTPS URL).
CUSTOM_SUPPORTED = True

# How much history to pull on first connect — the user's explicit, easy choice.
BACKFILL_DEPTHS = ("recent_30d", "recent_90d", "last_year", "everything")
DEFAULT_BACKFILL_DEPTH = "recent_90d"


def get_entry(catalog_id: str) -> CatalogEntry | None:
    return _BY_ID.get(catalog_id)


def catalog_payload(locale: str = "en") -> dict:
    """The full catalog as a JSON-able dict (clients pick the locale fields)."""
    return {
        "version": CATALOG_VERSION,
        "custom_supported": CUSTOM_SUPPORTED,
        "backfill_depths": list(BACKFILL_DEPTHS),
        "default_backfill_depth": DEFAULT_BACKFILL_DEPTH,
        "categories": [asdict(c) for c in CATEGORIES],
        "entries": [asdict(e) for e in ENTRIES],
    }
