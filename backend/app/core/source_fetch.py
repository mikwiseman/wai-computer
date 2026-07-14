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
- YouTube prefers captions (youtube-transcript-api, manual before generated,
  ru/en before other languages, optional proxy for blocked server IPs). When a
  video has no captions at all, the explicit audio fallback downloads the audio
  (yt-dlp) and runs the regular budget-guarded file-STT path — the result is
  labeled so replies can disclose it.

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


_YOUTUBE_PREFERRED_LANGUAGES = ["ru", "en"]


def _youtube_api():
    """Build a YouTubeTranscriptApi honoring the configured proxy (seam)."""
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
    """Choose the best transcript: ru/en first (manual before generated within
    each language per the library's ordering), then any manual, then any."""
    from youtube_transcript_api._errors import NoTranscriptFound

    try:
        return transcript_list.find_transcript(_YOUTUBE_PREFERRED_LANGUAGES)
    except NoTranscriptFound:
        pass
    manual = [t for t in transcript_list if not getattr(t, "is_generated", False)]
    if manual:
        return manual[0]
    any_transcripts = list(transcript_list)
    if any_transcripts:
        return any_transcripts[0]
    return None


def _fetch_youtube_transcript(
    video_id: str,
) -> tuple[str, str | None, list[dict]]:
    """Return (joined_text, language, time-coded segments) from captions.

    Raises SourceFetchError with a distinct, user-facing message per failure
    mode so the bot reply (and the audio fallback decision) can be precise.
    """
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        api = _youtube_api()
        transcript_list = api.list(video_id)
        transcript = _pick_transcript(transcript_list)
        if transcript is None:
            raise NoTranscriptFound(video_id, _YOUTUBE_PREFERRED_LANGUAGES, None)
        fetched = transcript.fetch()
    except (RequestBlocked, IpBlocked) as exc:
        # The message must stand on its own: it is what the user sees when the
        # audio fallback is disabled or unavailable (when the fallback runs,
        # this error is consumed and never shown).
        raise SourceFetchError(
            "YouTube is blocking transcript requests from this server. "
            "Share the file and I'll transcribe it.",
            code="youtube_blocked",
        ) from exc
    except TranscriptsDisabled as exc:
        raise SourceFetchError(
            "Subtitles are disabled for this video. Share the file and I'll "
            "transcribe it.",
            code="youtube_no_transcript",
        ) from exc
    except VideoUnavailable as exc:
        raise SourceFetchError(
            "This video is unavailable (private, removed, or region-locked).",
            code="youtube_unavailable",
        ) from exc
    except NoTranscriptFound as exc:
        raise SourceFetchError(
            "This video has no captions. Share the file and I'll "
            "transcribe it.",
            code="youtube_no_transcript",
        ) from exc
    except CouldNotRetrieveTranscript as exc:
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
    segments = _caption_segments(snippets)
    return text, language, segments


def _caption_segments(snippets) -> list[dict]:
    """Convert caption snippets to {content, start_ms, end_ms} segments so the
    key-moments table gets real video timestamps (deep-linkable)."""
    segments: list[dict] = []
    for s in snippets:
        content = (getattr(s, "text", "") or "").strip()
        if not content:
            continue
        start = float(getattr(s, "start", 0.0) or 0.0)
        duration = float(getattr(s, "duration", 0.0) or 0.0)
        segments.append(
            {
                "content": content,
                "start_ms": int(start * 1000),
                "end_ms": int((start + duration) * 1000),
            }
        )
    return segments


def _download_youtube_audio(url: str) -> tuple[bytes, str, float | None]:
    """Download a video's audio track via yt-dlp (seam for tests).

    Returns (audio_bytes, content_type, duration_seconds). Honors the
    configured proxy and the size/duration caps. Raises SourceFetchError with
    a user-facing message on every failure mode.
    """
    import tempfile
    from pathlib import Path

    import yt_dlp

    from app.config import get_settings

    settings = get_settings()
    max_bytes = settings.youtube_audio_max_bytes
    max_seconds = settings.youtube_audio_max_seconds

    def _too_long_filter(info, *, incomplete):
        duration = info.get("duration")
        if duration and max_seconds > 0 and duration > max_seconds:
            return f"video is longer than {max_seconds}s"
        return None

    with tempfile.TemporaryDirectory(prefix="yt-audio-") as tmp:
        opts: dict = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(Path(tmp) / "audio.%(ext)s"),
            "max_filesize": max_bytes,
            "match_filter": _too_long_filter,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        proxy_url = settings.youtube_proxy_url.strip()
        if proxy_url:
            opts["proxy"] = proxy_url
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise SourceFetchError(
                "Couldn't download this video's audio for transcription. "
                "Share the file and I'll transcribe it.",
                code="youtube_audio_download_failed",
            ) from exc

        files = sorted(Path(tmp).glob("audio.*"))
        if not files:
            raise SourceFetchError(
                "This video is longer or larger than the transcription limit. "
                "Share a shorter clip and I'll transcribe it.",
                code="youtube_audio_too_large",
            )
        data = files[0].read_bytes()
        if max_bytes > 0 and len(data) > max_bytes:
            raise SourceFetchError(
                "This video's audio exceeds the transcription size limit.",
                code="youtube_audio_too_large",
            )
        ext = files[0].suffix.lstrip(".").lower()
        content_type = {
            "m4a": "audio/mp4",
            "mp4": "audio/mp4",
            "webm": "audio/webm",
            "opus": "audio/ogg",
            "ogg": "audio/ogg",
            "mp3": "audio/mpeg",
        }.get(ext, "audio/mp4")
        duration = info.get("duration") if isinstance(info, dict) else None
        return data, content_type, float(duration) if duration else None


async def _transcribe_youtube_audio(
    url: str, video_id: str, stt_user_id: str
) -> tuple[str, str | None, list[dict]]:
    """No-captions recovery: download audio and run the guarded file-STT path.

    Returns (text, language, segments). The caller labels the result so user
    replies disclose that the transcript came from audio, not captions.
    """
    import asyncio

    from app.core.transcription import transcribe_audio_file

    data, content_type, duration = await asyncio.to_thread(
        _download_youtube_audio, url
    )
    transcription = await transcribe_audio_file(
        data,
        language="multi",
        content_type=content_type,
        user_id=stt_user_id,
        audio_duration_seconds=duration,
        usage_purpose="youtube_audio_fallback",
    )
    segments = [
        {
            "content": r.text,
            "start_ms": r.start_ms,
            "end_ms": r.end_ms,
        }
        for r in transcription.segments
        if (r.text or "").strip()
    ]
    text = " ".join(s["content"] for s in segments).strip()
    if not text:
        raise SourceFetchError(
            "No speech was detected in this video's audio.",
            code="youtube_audio_no_speech",
        )
    return text, None, segments


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


_AUDIO_FALLBACK_CODES = {"youtube_no_transcript", "youtube_blocked"}


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

    from app.config import get_settings

    transcript_source = "captions"
    try:
        text, language, segments = _fetch_youtube_transcript(vid)
    except SourceFetchError as exc:
        fallback_allowed = (
            get_settings().youtube_audio_fallback_enabled
            and stt_user_id is not None
            and exc.code in _AUDIO_FALLBACK_CODES
        )
        if not fallback_allowed:
            raise
        text, language, segments = await _transcribe_youtube_audio(
            url, vid, stt_user_id
        )
        transcript_source = "audio_stt"

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

    ``stt_user_id`` enables the budget-guarded YouTube audio fallback (the
    transcription minute budget is metered per user, so the fallback only runs
    when the caller can attribute the cost).
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
