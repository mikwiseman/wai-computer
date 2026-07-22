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
- YouTube prefers exact captions through the restricted edge egress. Videos
  without captions are analyzed from their public URL by Gemini. Neither path
  downloads media or uses account cookies.

Network/library calls live behind module-level functions so unit tests inject
fakes without hitting the network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urljoin, urlparse

from pydantic import BaseModel, Field

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
_TWITTER_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com", "mobile.twitter.com"}
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
MAX_FETCH_BYTES = 25 * 1024 * 1024
MAX_FETCH_REDIRECTS = 5


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
    if host in _TWITTER_HOSTS:
        return "twitter"
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


def _public_ip_address(address: ipaddress._BaseAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


def _resolve_host_addresses_sync(host: str) -> list[ipaddress._BaseAddress]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for info in infos:
        raw = info[4][0]
        if raw in seen:
            continue
        seen.add(raw)
        addresses.append(ipaddress.ip_address(raw))
    return addresses


async def _resolve_host_addresses(host: str) -> list[ipaddress._BaseAddress]:
    return await asyncio.to_thread(_resolve_host_addresses_sync, host)


async def _assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceFetchError(
            "Only public http(s) URLs can be fetched.",
            code="source_fetch_url_blocked",
        )
    addresses = await _resolve_host_addresses(parsed.hostname)
    if not addresses or any(not _public_ip_address(address) for address in addresses):
        raise SourceFetchError(
            "This URL resolves to a private or local network address.",
            code="source_fetch_url_blocked",
        )


async def _http_get(url: str) -> tuple[bytes, str]:
    """Fetch raw bytes + content-type for a URL (returns (body, content_type))."""
    import httpx

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=30.0,
        headers={"User-Agent": "WaiComputer/1.0 (+https://wai.computer)"},
    ) as client:
        current_url = url
        for _ in range(MAX_FETCH_REDIRECTS + 1):
            await _assert_public_http_url(current_url)
            async with client.stream("GET", current_url) as resp:
                if 300 <= resp.status_code < 400:
                    location = resp.headers.get("location") or resp.headers.get("Location")
                    if not location:
                        raise SourceFetchError(
                            "This URL redirected without a destination.",
                            code="source_fetch_redirect_invalid",
                        )
                    current_url = urljoin(current_url, location)
                    continue

                resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_FETCH_BYTES:
                        raise SourceFetchError(
                            "This source is larger than the fetch limit.",
                            code="source_fetch_too_large",
                        )
                    chunks.append(chunk)
                return b"".join(chunks), resp.headers.get("content-type", "")

        raise SourceFetchError(
            "This URL redirected too many times.",
            code="source_fetch_redirect_loop",
        )


class _GeminiVideoSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    content: str = Field(min_length=1)


class _GeminiVideoExtraction(BaseModel):
    language: str | None = None
    segments: list[_GeminiVideoSegment] = Field(min_length=1)


_YOUTUBE_EXTRACTION_PROMPT = """\
Create a faithful chronological representation of this public YouTube video for
search and later summarization.

- Preserve the original language. Do not translate.
- Preserve spoken facts, names, numbers, arguments, examples, decisions, and conclusions.
- Include important information that appears only visually.
- Divide the entire video into chronological segments at natural topic changes,
  normally 30-90 seconds each.
- Set accurate start_seconds and end_seconds for every segment.
- Write compact continuous prose, but do not omit material details.
- Never add information that is not present in the video.
- Return the detected BCP-47 language code when confident; otherwise null.
"""


_YOUTUBE_PREFERRED_LANGUAGES = ["ru", "en"]


def _youtube_api():
    """Build the captions client with the configured server egress proxy."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig

    from app.config import get_settings

    proxy_url = get_settings().youtube_proxy_url.strip()
    proxy_config = (
        GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
        if proxy_url
        else None
    )
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def _pick_transcript(transcript_list):
    """Prefer ru/en, then any manual transcript, then any generated one."""
    from youtube_transcript_api._errors import NoTranscriptFound

    try:
        return transcript_list.find_transcript(_YOUTUBE_PREFERRED_LANGUAGES)
    except NoTranscriptFound:
        pass
    transcripts = list(transcript_list)
    return next(
        (item for item in transcripts if not getattr(item, "is_generated", False)),
        transcripts[0] if transcripts else None,
    )


def _caption_segments(snippets) -> list[dict]:
    segments: list[dict] = []
    for snippet in snippets:
        content = (getattr(snippet, "text", "") or "").strip()
        if not content:
            continue
        start = float(getattr(snippet, "start", 0.0) or 0.0)
        duration = float(getattr(snippet, "duration", 0.0) or 0.0)
        segments.append(
            {
                "content": content,
                "start_ms": round(start * 1000),
                "end_ms": round((start + duration) * 1000),
            }
        )
    return segments


def _fetch_youtube_transcript(
    video_id: str,
) -> tuple[str, str | None, list[dict]]:
    """Return exact YouTube captions with time-coded segments."""
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        transcript_list = _youtube_api().list(video_id)
        transcript = _pick_transcript(transcript_list)
        if transcript is None:
            raise NoTranscriptFound(video_id, _YOUTUBE_PREFERRED_LANGUAGES, None)
        fetched = transcript.fetch()
    except (RequestBlocked, IpBlocked) as exc:
        raise SourceFetchError(
            "YouTube is blocking transcript requests from this server.",
            code="youtube_blocked",
        ) from exc
    except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript) as exc:
        raise SourceFetchError(
            "This video has no available captions.",
            code="youtube_no_transcript",
        ) from exc
    except VideoUnavailable as exc:
        raise SourceFetchError(
            "This video is unavailable (private, removed, or region-locked).",
            code="youtube_unavailable",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — normalized external API error
        raise SourceFetchError(
            "Couldn't fetch this YouTube video's captions right now.",
            code="youtube_fetch_failed",
        ) from exc

    snippets = list(fetched)
    segments = _caption_segments(snippets)
    text = " ".join(segment["content"] for segment in segments).strip()
    if not text:
        raise SourceFetchError(
            "This video's captions were empty.", code="youtube_empty"
        )
    return text, getattr(fetched, "language_code", None), segments


def _analyze_youtube_with_gemini(
    url: str,
) -> tuple[str, str | None, list[dict]]:
    """Analyze one public YouTube URL with Gemini's native video input."""
    from google import genai

    from app.config import get_settings

    settings = get_settings()
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        raise SourceFetchError(
            "YouTube link import is not configured on this server.",
            code="youtube_gemini_unconfigured",
        )

    client = genai.Client(api_key=api_key)
    try:
        interaction = client.interactions.create(
            model=settings.youtube_gemini_model,
            input=[
                {"type": "video", "uri": url, "resolution": "low"},
                {"type": "text", "text": _YOUTUBE_EXTRACTION_PROMPT},
            ],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _GeminiVideoExtraction.model_json_schema(),
            },
            store=False,
        )
        extraction = _GeminiVideoExtraction.model_validate_json(
            interaction.output_text
        )
    except Exception as exc:  # noqa: BLE001 — external API errors become user-safe
        raise SourceFetchError(
            "Couldn't analyze this YouTube video. Check that it is public and "
            "try again.",
            code="youtube_video_analysis_failed",
        ) from exc
    finally:
        client.close()

    segments: list[dict] = []
    for segment in extraction.segments:
        content = segment.content.strip()
        start_ms = round(segment.start_seconds * 1000)
        end_ms = round(segment.end_seconds * 1000)
        if end_ms < start_ms:
            raise SourceFetchError(
                "YouTube returned invalid video timestamps. Please try again.",
                code="youtube_video_analysis_invalid",
            )
        segments.append(
            {"content": content, "start_ms": start_ms, "end_ms": end_ms}
        )

    text = "\n\n".join(segment["content"] for segment in segments).strip()
    if not text:
        raise SourceFetchError(
            "No usable content was found in this YouTube video.",
            code="youtube_video_empty",
        )
    return text, extraction.language, segments


async def _fetch_youtube_with_gemini(
    url: str,
) -> tuple[str, str | None, list[dict]]:
    return await asyncio.to_thread(_analyze_youtube_with_gemini, url)


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


async def _youtube_oembed_title(url: str) -> str | None:
    """Video title via the public oEmbed endpoint. Best-effort: oEmbed is not
    gated by YouTube's anti-bot wall, but a miss must never fail the fetch."""
    import json as _json

    try:
        data, _ = await _http_get(
            "https://www.youtube.com/oembed?format=json&url=" + quote(url, safe="")
        )
        title = _json.loads(data.decode("utf-8", errors="replace")).get("title")
        return title.strip() if isinstance(title, str) and title.strip() else None
    except Exception:  # noqa: BLE001 — cosmetic metadata only
        return None


async def _fetch_youtube(url: str, stt_user_id: str | None = None) -> FetchedContent:
    vid = youtube_video_id(url)
    if not vid:
        raise SourceFetchError(
            "That doesn't look like a YouTube video link.", code="youtube_bad_url"
        )

    transcript_source = "captions"
    analysis_model = None
    try:
        text, language, segments = await asyncio.to_thread(
            _fetch_youtube_transcript, vid
        )
    except SourceFetchError as captions_error:
        if captions_error.code not in {
            "youtube_blocked",
            "youtube_no_transcript",
            "youtube_fetch_failed",
            "youtube_empty",
        }:
            raise
        canonical_url = f"https://www.youtube.com/watch?v={vid}"
        try:
            text, language, segments = await _fetch_youtube_with_gemini(
                canonical_url
            )
        except SourceFetchError as gemini_error:
            raise gemini_error from captions_error
        transcript_source = "gemini_video"
        from app.config import get_settings

        analysis_model = get_settings().youtube_gemini_model

    return FetchedContent(
        source_type="youtube",
        kind="video",
        url=url,
        # The real video title when oEmbed answers; otherwise the summarizer's
        # generated title fills the gap later.
        title=await _youtube_oembed_title(url),
        body=text,
        metadata={
            "video_id": vid,
            "language": language,
            "segments": segments,
            "transcript_source": transcript_source,
            **({"analysis_model": analysis_model} if analysis_model else {}),
        },
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


async def fetch_url(url: str, *, stt_user_id: str | None = None) -> FetchedContent:
    """Fetch + normalize content behind a URL. Raises SourceFetchError on failure.

    ``stt_user_id`` remains in the shared fetcher signature for callers that
    also process billable media; YouTube URL ingestion does not download media.
    """
    source_type = classify_url(url)
    if source_type == "youtube":
        return await _fetch_youtube(url, stt_user_id=stt_user_id)
    if source_type == "instagram":
        return await _fetch_blocked(url, "Instagram")
    if source_type == "tiktok":
        return await _fetch_blocked(url, "TikTok")
    if source_type == "twitter":
        raise SourceFetchError(
            "X (Twitter) doesn't allow apps to read posts. Paste the post text "
            "(or a screenshot) and I'll add it to your brain.",
            code="twitter_share_required",
        )
    if source_type == "pdf":
        return await _fetch_pdf(url)
    return await _fetch_article(url)
