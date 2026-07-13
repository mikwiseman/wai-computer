"""Title normalization for item-like content."""

from __future__ import annotations

_PLACEHOLDER_TITLES = {
    "",
    "untitled",
    "[untitled]",
    "без названия",
    "[без названия]",
}


def is_placeholder_title(value: str | None) -> bool:
    """Return true when a title is only a UI placeholder, not user content."""
    return (value or "").strip().casefold() in _PLACEHOLDER_TITLES


def clean_title(value: str | None, *, limit: int = 500) -> str | None:
    """Trim and drop known placeholders; return a DB-safe title or None."""
    title = (value or "").strip()
    if is_placeholder_title(title):
        return None
    return title[:limit]


def title_from_filename(filename: str | None) -> str | None:
    """Use the original uploaded filename as the first visible material title."""
    base = (filename or "").strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = (base.rsplit(".", 1)[0] if "." in base else base).strip()
    return clean_title(stem)


def title_from_body(body: str | None, *, limit: int = 64) -> str | None:
    """Derive a display-only title from the first words of the body.

    Presentation fallback for items whose real title hasn't been generated
    yet (or never will be) — the stored title stays NULL so the summarizer's
    title can still land later.
    """
    text = " ".join((body or "").split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
