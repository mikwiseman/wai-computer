"""Shared Telegram HTML formatting helpers (parse_mode='HTML').

Pure and model-agnostic so the bot's recording, item, and any future renderers
share ONE tested markdown->HTML converter. The bot sends with parse_mode='HTML'
but the summarizer emits lightweight markdown (``**bold**``, ``- bullets``);
without conversion Telegram shows the literal asterisks. ``telegram_html`` does
that conversion AND keeps the older "a line ending in ':' is a header" fallback
so colon-style headers still bold.
"""

from __future__ import annotations

import re
from html import escape

# Inline emphasis. Applied AFTER html.escape, so ``*``/``_`` are still literal
# while ``<``/``>``/``&`` are already entities.
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD_US_RE = re.compile(r"__(.+?)__")
# Single ``*emphasis*`` -> italic, but never a stray ``*`` (e.g. ``2 * 3``) and
# never snake_case ``_`` inside a word.
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<![\s\*])\*(?!\*)")
_ITALIC_US_RE = re.compile(r"(?<![_\w])_(?!\s)(.+?)(?<![\s_])_(?!\w)")
# ``` `monospace` ``` for numbers/amounts/dates (the scannable-metrics look).
_CODE_RE = re.compile(r"`([^`\n]+)`")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_LEADING_BULLET_RE = re.compile(r"^([-*•–])\s+")


def _convert_emphasis(text: str) -> tuple[str, bool]:
    produced_bold = bool(_BOLD_STAR_RE.search(text) or _BOLD_US_RE.search(text))
    text = _BOLD_STAR_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_US_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_US_RE.sub(r"<i>\1</i>", text)
    return text, produced_bold


def _convert_inline(text: str) -> tuple[str, bool]:
    """Convert inline markdown emphasis to HTML. Returns (html, produced_bold).

    Code spans convert first and are opaque to the emphasis passes, so a ``*``
    or ``_`` inside backticks never becomes a stray tag.
    """
    parts: list[str] = []
    produced_bold = False
    cursor = 0
    for match in _CODE_RE.finditer(text):
        before, before_bold = _convert_emphasis(text[cursor : match.start()])
        parts.append(before)
        produced_bold = produced_bold or before_bold
        parts.append(f"<code>{match.group(1)}</code>")
        cursor = match.end()
    tail, tail_bold = _convert_emphasis(text[cursor:])
    parts.append(tail)
    return "".join(parts), produced_bold or tail_bold


def telegram_html(text: str) -> str:
    """Render lightweight-markdown summary text as Telegram HTML.

    - HTML-escapes first (model/user content can't inject tags).
    - ``**bold**``/``__bold__`` -> ``<b>``; ``*italic*``/``_italic_`` -> ``<i>``.
    - Normalizes leading bullet markers (``-``, ``*``, ``•``, ``–``) to ``•``.
    - Markdown ``#`` headings -> bold.
    - Fallback: a NON-bulleted line that ends with ':' and produced no bold of
      its own is bolded as a header (keeps prior colon-header behavior).
    """
    if not text:
        return ""
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            lines.append("")
            continue

        escaped = escape(stripped)

        heading = _HEADING_RE.match(escaped)
        if heading:
            inline, _ = _convert_inline(escaped[heading.end() :].strip())
            lines.append(f"<b>{inline}</b>")
            continue

        bullet = _LEADING_BULLET_RE.match(escaped)
        if bullet:
            # Preserve the author's marker (Image-1 style uses '- ' dashes), only
            # convert inline emphasis and skip the colon-header fallback.
            marker = bullet.group(1)
            inline, _ = _convert_inline(escaped[bullet.end() :])
            lines.append(f"{marker} {inline}")
            continue

        inline, produced_bold = _convert_inline(escaped)
        if not produced_bold and inline.endswith(":"):
            lines.append(f"<b>{inline}</b>")
        else:
            lines.append(inline)

    return "\n".join(lines).strip()


def telegram_inline(text: str) -> str:
    """Escape + convert inline emphasis for a SINGLE value (label, task, title).

    Unlike ``telegram_html`` this applies no bullet/heading/colon-header line
    logic — use it for one-liners where a trailing ':' must NOT bold the value.
    """
    if not text:
        return ""
    inline, _ = _convert_inline(escape(text.strip()))
    return inline
