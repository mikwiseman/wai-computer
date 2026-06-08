"""Format an ingested Item as a Telegram reply (summary + key-moments table).

Kept separate from the telegram route so the formatting is unit-testable
without a bot client. HTML parse-mode (matching the rest of the bot).
"""

from __future__ import annotations

from html import escape

from app.core.telegram_format import telegram_html, telegram_inline
from app.models.item import Item, ItemSummary

_MAX_MOMENTS = 8


def format_item_reply(item: Item, summary: ItemSummary | None) -> str:
    """Build the HTML reply body for a forwarded link / pasted content.

    Layout: title, one-paragraph summary, then a compact key-moments list
    (Telegram has no real tables, so each moment is a line: ``• [ts] moment``).
    """
    sections: list[str] = []

    title = (item.title or "").strip()
    if title:
        sections.append(f"<b>{telegram_inline(title)}</b>")

    if summary is not None and (summary.summary or "").strip():
        sections.append(telegram_html(summary.summary.strip()))

    moments = (summary.key_moments if summary else None) or []
    if moments:
        lines = ["<b>Key moments</b>"]
        for moment in moments[:_MAX_MOMENTS]:
            label = telegram_inline(str(moment.get("moment") or "").strip())
            if not label:
                continue
            ts = str(moment.get("timestamp") or "").strip()
            prefix = f"[{escape(ts)}] " if ts else "• "
            lines.append(f"{prefix}{label}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    action_items = (summary.action_items if summary else None) or []
    todo_lines = [
        telegram_inline(str(a.get("task") or "").strip())
        for a in action_items
        if str(a.get("task") or "").strip()
    ]
    if todo_lines:
        sections.append(
            "<b>To do</b>\n" + "\n".join(f"☐ {t}" for t in todo_lines[:_MAX_MOMENTS])
        )

    body = "\n\n".join(s for s in sections if s).strip()
    if not body:
        return "Saved to your brain."
    return body


def format_fetch_error_reply(message: str) -> str:
    """Reply when a URL couldn't be fetched (e.g. Instagram/TikTok)."""
    return escape(message)
