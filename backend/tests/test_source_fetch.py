"""Unit tests for source fetchers (URL classification + dispatch + errors).

Network/library seams are patched so these run offline.
"""

import ipaddress
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.core import source_fetch
from app.core.source_fetch import (
    SourceFetchError,
    _public_ip_address,
    _resolve_host_addresses,
    _resolve_host_addresses_sync,
    classify_url,
    fetch_url,
    find_first_url,
    youtube_video_id,
)

# --- URL helpers (pure, sync) ----------------------------------------------


def test_find_first_url() -> None:
    assert find_first_url("watch this https://youtu.be/abc123XYZ99 cool") == (
        "https://youtu.be/abc123XYZ99"
    )
    assert find_first_url("no link here") is None
    assert find_first_url(None) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://youtube.com/watch?v=abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://www.instagram.com/reel/xyz/", "instagram"),
        ("https://www.tiktok.com/@u/video/1", "tiktok"),
        ("https://x.com/user/status/123", "twitter"),
        ("https://twitter.com/user/status/123", "twitter"),
        ("https://example.com/file.pdf", "pdf"),
        ("https://example.com/blog/post", "article"),
    ],
)
def test_classify_url(url: str, expected: str) -> None:
    assert classify_url(url) == expected


@pytest.mark.parametrize(
    "url,vid",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/abc123", "abc123"),
        ("https://www.youtube.com/embed/xyz789", "xyz789"),
        ("https://example.com/not-youtube", None),
    ],
)
def test_youtube_video_id(url: str, vid: str | None) -> None:
    assert youtube_video_id(url) == vid


def test_public_ip_address_handles_ipv6_mapped_ipv4() -> None:
    assert _public_ip_address(ipaddress.ip_address("::ffff:8.8.8.8")) is True
    assert _public_ip_address(ipaddress.ip_address("::ffff:10.0.0.1")) is False


@pytest.mark.asyncio
async def test_resolve_host_addresses_dedupes_socket_results(monkeypatch) -> None:
    infos = [
        (None, None, None, None, ("8.8.8.8", 0)),
        (None, None, None, None, ("8.8.8.8", 0)),
        (None, None, None, None, ("1.1.1.1", 0)),
    ]
    monkeypatch.setattr(source_fetch.socket, "getaddrinfo", lambda *args, **kwargs: infos)

    expected = [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("1.1.1.1")]
    assert _resolve_host_addresses_sync("host") == expected
    assert await _resolve_host_addresses("host") == expected


class _FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self._chunks = chunks or [b"<html>hi</html>"]

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_http_get_rejects_non_http_urls() -> None:
    with pytest.raises(SourceFetchError) as ei:
        await source_fetch._http_get("file:///etc/passwd")
    assert ei.value.code == "source_fetch_url_blocked"


@pytest.mark.asyncio
async def test_http_get_rejects_private_resolved_addresses(monkeypatch) -> None:
    async def private_addresses(_host: str):
        return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(source_fetch, "_resolve_host_addresses", private_addresses)

    with pytest.raises(SourceFetchError) as ei:
        await source_fetch._http_get("https://example.com/post")
    assert ei.value.code == "source_fetch_url_blocked"


@pytest.mark.asyncio
async def test_http_get_revalidates_redirect_targets(monkeypatch) -> None:
    async def addresses(host: str):
        if host == "example.com":
            return [ipaddress.ip_address("93.184.216.34")]
        return [ipaddress.ip_address("169.254.169.254")]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, _method, _url):
            return _FakeStream(
                _FakeResponse(
                    status_code=302,
                    headers={"location": "http://169.254.169.254/latest"},
                    chunks=[],
                )
            )

    monkeypatch.setattr(source_fetch, "_resolve_host_addresses", addresses)
    with patch.dict("sys.modules", {"httpx": SimpleNamespace(AsyncClient=FakeClient)}):
        with pytest.raises(SourceFetchError) as ei:
            await source_fetch._http_get("https://example.com/post")
    assert ei.value.code == "source_fetch_url_blocked"


@pytest.mark.asyncio
async def test_http_get_enforces_response_size_cap(monkeypatch) -> None:
    async def public_addresses(_host: str):
        return [ipaddress.ip_address("93.184.216.34")]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, _method, _url):
            return _FakeStream(
                _FakeResponse(chunks=[b"x" * (source_fetch.MAX_FETCH_BYTES + 1)])
            )

    monkeypatch.setattr(source_fetch, "_resolve_host_addresses", public_addresses)
    with patch.dict("sys.modules", {"httpx": SimpleNamespace(AsyncClient=FakeClient)}):
        with pytest.raises(SourceFetchError) as ei:
            await source_fetch._http_get("https://example.com/post")
    assert ei.value.code == "source_fetch_too_large"


# --- Dispatch + errors (async) ---------------------------------------------


@pytest.mark.asyncio
async def test_instagram_raises_share_required() -> None:
    with pytest.raises(SourceFetchError) as ei:
        await fetch_url("https://www.instagram.com/reel/abc/")
    assert ei.value.code == "instagram_share_required"
    assert "Instagram" in ei.value.message


@pytest.mark.asyncio
async def test_tiktok_raises_share_required() -> None:
    with pytest.raises(SourceFetchError) as ei:
        await fetch_url("https://www.tiktok.com/@u/video/1")
    assert ei.value.code == "tiktok_share_required"


@pytest.mark.asyncio
async def test_twitter_raises_share_required() -> None:
    # X's anti-bot wall makes article extraction junk — the refusal must be
    # explicit and actionable, like Instagram/TikTok.
    with pytest.raises(SourceFetchError) as ei:
        await fetch_url("https://x.com/user/status/123")
    assert ei.value.code == "twitter_share_required"
    assert "X (Twitter)" in ei.value.message


_CAPTION_SEGMENTS = [
    {"content": "hello world", "start_ms": 0, "end_ms": 2000},
    {"content": "transcript", "start_ms": 2000, "end_ms": 3500},
]


@pytest.mark.asyncio
async def test_youtube_fetches_video_with_gemini() -> None:
    def _no_captions(_video_id: str):
        raise SourceFetchError("no captions", code="youtube_no_transcript")

    async def _fake_gemini(url: str):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        return "hello world transcript", "en", _CAPTION_SEGMENTS

    with patch.object(
        source_fetch,
        "_fetch_youtube_transcript",
        side_effect=_no_captions,
    ), patch.object(
        source_fetch,
        "_fetch_youtube_with_gemini",
        side_effect=_fake_gemini,
        create=True,
    ), patch.object(
        source_fetch,
        "_youtube_oembed_title",
        return_value="Never Gonna Give You Up",
    ):
        content = await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert content.source_type == "youtube"
    assert content.kind == "video"
    assert content.body == "hello world transcript"
    # Captions carry no video title — oEmbed fills it in.
    assert content.title == "Never Gonna Give You Up"
    assert content.metadata["video_id"] == "dQw4w9WgXcQ"
    assert content.metadata["language"] == "en"
    assert content.metadata["transcript_source"] == "gemini_video"
    assert content.metadata["segments"] == _CAPTION_SEGMENTS


@pytest.mark.asyncio
async def test_youtube_prefers_exact_captions() -> None:
    async def _gemini_must_not_run(_url: str):  # pragma: no cover
        raise AssertionError("Gemini must not replace exact captions")

    with patch.object(
        source_fetch,
        "_fetch_youtube_transcript",
        return_value=("exact captions", "iw", _CAPTION_SEGMENTS),
    ), patch.object(
        source_fetch,
        "_fetch_youtube_with_gemini",
        side_effect=_gemini_must_not_run,
    ), patch.object(source_fetch, "_youtube_oembed_title", return_value="Title"):
        content = await fetch_url("https://youtu.be/ERthxTL2qfw?si=tracking")

    assert content.body == "exact captions"
    assert content.metadata["language"] == "iw"
    assert content.metadata["transcript_source"] == "captions"
    assert "analysis_model" not in content.metadata


@pytest.mark.asyncio
async def test_youtube_title_is_best_effort() -> None:
    """An oEmbed miss must never fail the fetch — the summarizer titles later."""

    async def _oembed_down(_url):
        raise RuntimeError("network down")

    with patch.object(
        source_fetch,
        "_fetch_youtube_transcript",
        return_value=("hello world transcript", "en", _CAPTION_SEGMENTS),
    ), patch.object(source_fetch, "_http_get", side_effect=_oembed_down):
        content = await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert content.title is None
    assert content.body == "hello world transcript"


def test_fetch_youtube_transcript_uses_generated_caption_segments() -> None:
    from youtube_transcript_api._errors import NoTranscriptFound

    class Fetched(list):
        language_code = "iw"

    fetched = Fetched(
        [
            SimpleNamespace(text="שלום", start=0.199, duration=1.201),
            SimpleNamespace(text="  ", start=1.4, duration=0.2),
            SimpleNamespace(text="עולם", start=1.6, duration=2.0),
        ]
    )
    transcript = SimpleNamespace(is_generated=True, fetch=lambda: fetched)

    class TranscriptList:
        def find_transcript(self, _languages):
            raise NoTranscriptFound("vid", [], None)

        def __iter__(self):
            return iter([transcript])

    api = SimpleNamespace(list=lambda _video_id: TranscriptList())
    with patch.object(source_fetch, "_youtube_api", return_value=api):
        text, language, segments = source_fetch._fetch_youtube_transcript("vid")

    assert text == "שלום עולם"
    assert language == "iw"
    assert segments == [
        {"content": "שלום", "start_ms": 199, "end_ms": 1400},
        {"content": "עולם", "start_ms": 1600, "end_ms": 3600},
    ]


def test_fetch_youtube_transcript_maps_blocked_request() -> None:
    from youtube_transcript_api._errors import RequestBlocked

    api = SimpleNamespace(list=Mock(side_effect=RequestBlocked("vid")))
    with patch.object(source_fetch, "_youtube_api", return_value=api):
        with pytest.raises(SourceFetchError) as ei:
            source_fetch._fetch_youtube_transcript("vid")
    assert ei.value.code == "youtube_blocked"


@pytest.mark.asyncio
async def test_youtube_unavailable_does_not_call_gemini() -> None:
    def _unavailable(_video_id: str):
        raise SourceFetchError("unavailable", code="youtube_unavailable")

    async def _gemini_must_not_run(_url: str):  # pragma: no cover
        raise AssertionError("Gemini must not hide an unavailable video")

    with patch.object(
        source_fetch, "_fetch_youtube_transcript", side_effect=_unavailable
    ), patch.object(
        source_fetch, "_fetch_youtube_with_gemini", side_effect=_gemini_must_not_run
    ):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert ei.value.code == "youtube_unavailable"


def test_analyze_youtube_with_gemini_returns_timed_segments(monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "youtube_gemini_model", "gemini-3.6-flash")
    interaction = SimpleNamespace(
        output_text=(
            '{"language":"he","segments":['
            '{"start_seconds":0,"end_seconds":12.5,"content":"פתיחה"},'
            '{"start_seconds":12.5,"end_seconds":30,"content":"דיון"}]}'
        )
    )
    create = Mock(return_value=interaction)
    client = SimpleNamespace(
        interactions=SimpleNamespace(create=create), close=Mock()
    )

    with patch("google.genai.Client", return_value=client):
        text, language, segments = source_fetch._analyze_youtube_with_gemini(
            "https://youtu.be/ERthxTL2qfw"
        )

    assert text == "פתיחה\n\nדיון"
    assert language == "he"
    assert segments == [
        {"content": "פתיחה", "start_ms": 0, "end_ms": 12_500},
        {"content": "דיון", "start_ms": 12_500, "end_ms": 30_000},
    ]
    request = create.call_args.kwargs
    assert request["model"] == "gemini-3.6-flash"
    assert request["store"] is False
    assert request["input"][0] == {
        "type": "video",
        "uri": "https://youtu.be/ERthxTL2qfw",
        "resolution": "low",
    }
    assert request["response_format"]["mime_type"] == "application/json"
    client.close.assert_called_once_with()


def test_analyze_youtube_with_gemini_requires_key(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    with pytest.raises(SourceFetchError) as ei:
        source_fetch._analyze_youtube_with_gemini("https://youtu.be/abc")
    assert ei.value.code == "youtube_gemini_unconfigured"


def test_analyze_youtube_with_gemini_surfaces_api_failure(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    client = SimpleNamespace(
        interactions=SimpleNamespace(create=Mock(side_effect=RuntimeError("down"))),
        close=Mock(),
    )
    with patch("google.genai.Client", return_value=client):
        with pytest.raises(SourceFetchError) as ei:
            source_fetch._analyze_youtube_with_gemini("https://youtu.be/abc")
    assert ei.value.code == "youtube_video_analysis_failed"
    client.close.assert_called_once_with()


def test_analyze_youtube_with_gemini_rejects_invalid_timestamps(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    interaction = SimpleNamespace(
        output_text=(
            '{"language":null,"segments":['
            '{"start_seconds":10,"end_seconds":5,"content":"bad"}]}'
        )
    )
    client = SimpleNamespace(
        interactions=SimpleNamespace(create=Mock(return_value=interaction)),
        close=Mock(),
    )
    with patch("google.genai.Client", return_value=client):
        with pytest.raises(SourceFetchError) as ei:
            source_fetch._analyze_youtube_with_gemini("https://youtu.be/abc")
    assert ei.value.code == "youtube_video_analysis_invalid"


@pytest.mark.asyncio
async def test_article_fetches_and_extracts() -> None:
    async def fake_get(_url):
        return b"<html><body><article>Long body text</article></body></html>", "text/html"

    with (
        patch.object(source_fetch, "_http_get", side_effect=fake_get),
        patch.object(
            source_fetch, "_extract_article", return_value=("My Title", "Long body text")
        ),
    ):
        content = await fetch_url("https://example.com/post")
    assert content.source_type == "article"
    assert content.title == "My Title"
    assert content.body == "Long body text"


@pytest.mark.asyncio
async def test_article_empty_extract_raises() -> None:
    async def fake_get(_url):
        return b"<html></html>", "text/html"

    with (
        patch.object(source_fetch, "_http_get", side_effect=fake_get),
        patch.object(source_fetch, "_extract_article", return_value=(None, None)),
    ):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://example.com/empty")
    assert ei.value.code == "article_empty"


@pytest.mark.asyncio
async def test_article_url_serving_pdf_is_parsed_as_pdf() -> None:
    async def fake_get(_url):
        return b"%PDF-1.7 fake", "application/pdf"

    with (
        patch.object(source_fetch, "_http_get", side_effect=fake_get),
        patch.object(source_fetch, "_extract_pdf_text", return_value="pdf body text"),
    ):
        content = await fetch_url("https://example.com/whatever")
    assert content.source_type == "pdf"
    assert content.body == "pdf body text"


@pytest.mark.asyncio
async def test_pdf_url_no_text_raises() -> None:
    async def fake_get(_url):
        return b"%PDF-1.7", "application/pdf"

    with (
        patch.object(source_fetch, "_http_get", side_effect=fake_get),
        patch.object(source_fetch, "_extract_pdf_text", return_value=""),
    ):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://example.com/scan.pdf")
    assert ei.value.code == "pdf_no_text"
