"""Source fetchers: turn a forwarded/pasted URL into summarizable text.

The hero "forward a link -> summary + key-moments table" loop needs to pull the
actual content behind a URL. This module classifies a URL and dispatches to a
per-source fetcher, returning a normalized ``FetchedContent`` that the item
ingestion + summarizer pipeline consumes.

Design (per AGENTS.md "no silent fallback"):
- Every fetcher either returns content or raises ``SourceFetchError`` with a
  clear, user-facing ``message`` — we never return a half-empty result that
  looks like success.
- Instagram and TikTok forbid programmatic content extraction, so we DO NOT
  scrape them; we raise ``SourceFetchError`` asking the user to share the file
  or paste the caption. (ToS-safe by design.)
- YouTube uses captions only (youtube-transcript-api, instance API); audio
  download -> Deepgram is a later enhancement.

Network/library calls live behind module-level functions so unit tests inject
fakes without hitting the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------------


@dataclass
class FetchedContent:
    """Normalized output of a source fetch — feeds item ingestion."""

    source_type: str  # youtube | article | pdf | podcast | ...
    kind: str  # video | article | pdf | podcast | ...
    url: str
    title: str | None = None
    body: str | None = None
    metadata: dict = field(default_factory=dict)


class SourceFetchError(Exception):
    """A fetch could not complete. ``message`` is safe to show the user."""

    def __init__(self, message: str, *, code: str = "fetch_failed"):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
_TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "vm.tiktok.com"}
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def find_first_url(text: str | None) -> str | None:
    """Return the first http(s) URL in a blob of text, or None.

    Used by the Telegram forward path to detect a link in a message.
    """
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def classify_url(url: str) -> str:
    """Classify a URL into a source type (youtube/instagram/tiktok/pdf/article)."""
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    if host in _INSTAGRAM_HOSTS:
        return "instagram"
    if host in _TIKTOK_HOSTS:
        return "tiktok"
    if path.endswith(".pdf"):
        return "pdf"
    return "article"


def youtube_video_id(url: str) -> str | None:
    """Extract the 11-char video id from common YouTube URL shapes."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid or None
    if host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            vals = parse_qs(parsed.query).get("v")
            return vals[0] if vals else None
        for prefix in ("/embed/", "/shorts/", "/v/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0] or None
    return None


# ---------------------------------------------------------------------------
# Network/library seams (patched in tests)
# ---------------------------------------------------------------------------


async def _http_get(url: str) -> tuple[bytes, str]:
    """Fetch raw bytes + content-type for a URL (returns (body, content_type))."""
    import httpx

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": "WaiComputer/1.0 (+https://wai.computer)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "")


def _fetch_youtube_transcript(video_id: str) -> tuple[str, str | None]:
    """Return (joined_transcript_text, language) using the v1.x instance API.

    Raises SourceFetchError with a friendly message on the known failure modes.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        VideoUnavailable,
    )

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
    except (CouldNotRetrieveTranscript, VideoUnavailable) as exc:
        raise SourceFetchError(
            "This video has no available transcript. Share the file and I'll "
            "transcribe it.",
            code="youtube_no_transcript",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface as a clean user error
        raise SourceFetchError(
            "Couldn't fetch this YouTube video's transcript right now.",
            code="youtube_fetch_failed",
        ) from exc

    snippets = list(fetched)
    text = " ".join(getattr(s, "text", "") for s in snippets).strip()
    language = getattr(fetched, "language_code", None)
    if not text:
        raise SourceFetchError(
            "This video's transcript was empty.", code="youtube_empty"
        )
    return text, language


def _extract_article(html: str, url: str) -> tuple[str | None, str | None]:
    """Return (title, body_markdown) from article HTML via trafilatura."""
    import trafilatura

    body = trafilatura.extract(
        html,
        url=url,
        favor_precision=True,
        include_comments=False,
        include_tables=True,
        output_format="markdown",
    )
    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta is not None:
            title = getattr(meta, "title", None)
    except Exception:  # noqa: BLE001 — metadata is best-effort
        title = None
    return title, body


def _extract_pdf_text(data: bytes) -> str:
    """Extract plain text from PDF bytes via pdfplumber (pure-Python)."""
    import io

    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n\n".join(p for p in parts if p.strip()).strip()


def _pdf_page_count(data: bytes) -> int:
    """Number of pages in a PDF — used to bound inline OCR cost."""
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


# ---------------------------------------------------------------------------
# Per-source fetchers
# ---------------------------------------------------------------------------


async def _fetch_youtube(url: str) -> FetchedContent:
    vid = youtube_video_id(url)
    if not vid:
        raise SourceFetchError(
            "That doesn't look like a YouTube video link.", code="youtube_bad_url"
        )
    text, language = _fetch_youtube_transcript(vid)
    return FetchedContent(
        source_type="youtube",
        kind="video",
        url=url,
        title=None,  # filled by the summarizer's generated title
        body=text,
        metadata={"video_id": vid, "language": language},
    )


async def _fetch_article(url: str) -> FetchedContent:
    raw, content_type = await _http_get(url)
    if "application/pdf" in content_type.lower():
        return await _fetch_pdf_bytes(url, raw)
    html = raw.decode("utf-8", errors="replace")
    title, body = _extract_article(html, url)
    if not body or not body.strip():
        raise SourceFetchError(
            "Couldn't extract readable text from that page. Paste the text and "
            "I'll summarize it.",
            code="article_empty",
        )
    return FetchedContent(
        source_type="article",
        kind="article",
        url=url,
        title=title,
        body=body,
        metadata={},
    )


async def _fetch_pdf_bytes(url: str, data: bytes) -> FetchedContent:
    text = _extract_pdf_text(data)
    if not text:
        raise SourceFetchError(
            "This PDF has no extractable text (it may be scanned images).",
            code="pdf_no_text",
        )
    return FetchedContent(
        source_type="pdf", kind="pdf", url=url, title=None, body=text, metadata={}
    )


async def _fetch_pdf(url: str) -> FetchedContent:
    data, _ = await _http_get(url)
    return await _fetch_pdf_bytes(url, data)


_SHARE_FILE_MESSAGE = (
    "{platform} doesn't allow apps to read its posts. Share the video or photo "
    "directly (or paste the caption) and I'll add it to your brain."
)


async def _fetch_blocked(url: str, platform: str) -> FetchedContent:
    raise SourceFetchError(
        _SHARE_FILE_MESSAGE.format(platform=platform),
        code=f"{platform.lower()}_share_required",
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def fetch_url(url: str) -> FetchedContent:
    """Fetch + normalize content behind a URL. Raises SourceFetchError on failure."""
    source_type = classify_url(url)
    if source_type == "youtube":
        return await _fetch_youtube(url)
    if source_type == "instagram":
        return await _fetch_blocked(url, "Instagram")
    if source_type == "tiktok":
        return await _fetch_blocked(url, "TikTok")
    if source_type == "pdf":
        return await _fetch_pdf(url)
    return await _fetch_article(url)
