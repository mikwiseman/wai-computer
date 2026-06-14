"""Unit tests for source fetchers (URL classification + dispatch + errors).

Network/library seams are patched so these run offline.
"""

import ipaddress
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core import source_fetch
from app.core.source_fetch import (
    SourceFetchError,
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


_CAPTION_SEGMENTS = [
    {"content": "hello world", "start_ms": 0, "end_ms": 2000},
    {"content": "transcript", "start_ms": 2000, "end_ms": 3500},
]


@pytest.mark.asyncio
async def test_youtube_fetches_transcript() -> None:
    with patch.object(
        source_fetch,
        "_fetch_youtube_transcript",
        return_value=("hello world transcript", "en", _CAPTION_SEGMENTS),
    ):
        content = await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert content.source_type == "youtube"
    assert content.kind == "video"
    assert content.body == "hello world transcript"
    assert content.metadata["video_id"] == "dQw4w9WgXcQ"
    assert content.metadata["language"] == "en"
    assert content.metadata["transcript_source"] == "captions"
    assert content.metadata["segments"] == _CAPTION_SEGMENTS


@pytest.mark.asyncio
async def test_youtube_no_transcript_propagates_friendly_error() -> None:
    """Without a user to bill STT to, the no-captions error surfaces as-is."""

    def _boom(_vid):
        raise SourceFetchError("no transcript", code="youtube_no_transcript")

    with patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_boom):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert ei.value.code == "youtube_no_transcript"


@pytest.mark.asyncio
async def test_youtube_no_captions_falls_back_to_audio_stt() -> None:
    """No captions + a billable user -> audio download + file STT, disclosed."""

    def _boom(_vid):
        raise SourceFetchError("no transcript", code="youtube_no_transcript")

    async def _fake_stt(url, vid, stt_user_id):
        assert vid == "dQw4w9WgXcQ"
        assert stt_user_id == "user-1"
        return (
            "spoken words",
            None,
            [{"content": "spoken words", "start_ms": 0, "end_ms": 1500}],
        )

    with (
        patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_boom),
        patch.object(source_fetch, "_transcribe_youtube_audio", side_effect=_fake_stt),
    ):
        content = await fetch_url(
            "https://youtu.be/dQw4w9WgXcQ", stt_user_id="user-1"
        )
    assert content.body == "spoken words"
    assert content.metadata["transcript_source"] == "audio_stt"


@pytest.mark.asyncio
async def test_youtube_blocked_falls_back_to_audio_stt() -> None:
    """A blocked server IP also tries the audio path before giving up."""

    def _blocked(_vid):
        raise SourceFetchError("blocked", code="youtube_blocked")

    async def _fake_stt(url, vid, stt_user_id):
        return ("recovered", None, [])

    with (
        patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_blocked),
        patch.object(source_fetch, "_transcribe_youtube_audio", side_effect=_fake_stt),
    ):
        content = await fetch_url(
            "https://youtu.be/dQw4w9WgXcQ", stt_user_id="user-1"
        )
    assert content.metadata["transcript_source"] == "audio_stt"


@pytest.mark.asyncio
async def test_youtube_unavailable_does_not_fall_back() -> None:
    """Private/removed videos can't be recovered by downloading audio."""

    def _gone(_vid):
        raise SourceFetchError("gone", code="youtube_unavailable")

    async def _should_not_run(url, vid, stt_user_id):  # pragma: no cover
        raise AssertionError("audio fallback must not run for unavailable videos")

    with (
        patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_gone),
        patch.object(
            source_fetch, "_transcribe_youtube_audio", side_effect=_should_not_run
        ),
    ):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://youtu.be/dQw4w9WgXcQ", stt_user_id="user-1")
    assert ei.value.code == "youtube_unavailable"


@pytest.mark.asyncio
async def test_youtube_fallback_disabled_by_config(monkeypatch) -> None:
    from app.config import get_settings

    def _boom(_vid):
        raise SourceFetchError("no transcript", code="youtube_no_transcript")

    settings = get_settings()
    monkeypatch.setattr(settings, "youtube_audio_fallback_enabled", False)
    with patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_boom):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://youtu.be/dQw4w9WgXcQ", stt_user_id="user-1")
    assert ei.value.code == "youtube_no_transcript"


def test_pick_transcript_prefers_ru_en_then_manual_then_any() -> None:
    from youtube_transcript_api._errors import NoTranscriptFound

    class FakeTranscript:
        def __init__(self, language_code, is_generated):
            self.language_code = language_code
            self.is_generated = is_generated

    class FakeList:
        def __init__(self, transcripts, preferred=None):
            self._transcripts = transcripts
            self._preferred = preferred

        def __iter__(self):
            return iter(self._transcripts)

        def find_transcript(self, codes):
            if self._preferred is not None:
                return self._preferred
            raise NoTranscriptFound("vid", codes, None)

    ru = FakeTranscript("ru", False)
    de_manual = FakeTranscript("de", False)
    fr_auto = FakeTranscript("fr", True)

    # Preferred language wins when available.
    assert source_fetch._pick_transcript(FakeList([fr_auto, ru], preferred=ru)) is ru
    # No ru/en -> first manually created transcript.
    assert (
        source_fetch._pick_transcript(FakeList([fr_auto, de_manual])) is de_manual
    )
    # Only auto-generated left -> take it rather than failing.
    assert source_fetch._pick_transcript(FakeList([fr_auto])) is fr_auto
    # Nothing at all -> None (caller raises the friendly error).
    assert source_fetch._pick_transcript(FakeList([])) is None


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


# --- Audio fallback helpers (seams mocked) ----------------------------------


def test_youtube_api_uses_proxy_when_configured(monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "youtube_proxy_url", "http://user:pass@proxy:1000")
    api = source_fetch._youtube_api()
    assert api is not None  # constructed with GenericProxyConfig without raising

    monkeypatch.setattr(settings, "youtube_proxy_url", "")
    assert source_fetch._youtube_api() is not None


@pytest.mark.asyncio
async def test_transcribe_youtube_audio_builds_segments(monkeypatch) -> None:
    from app.core.transcript_utils import TranscriptResult

    def fake_download(url):
        return b"audio-bytes", "audio/mp4", 12.5

    async def fake_stt(data, **kwargs):
        assert data == b"audio-bytes"
        assert kwargs["user_id"] == "u1"
        assert kwargs["content_type"] == "audio/mp4"
        assert kwargs["audio_duration_seconds"] == 12.5
        return [
            TranscriptResult(
                text="hello", speaker=None, is_final=True,
                start_ms=0, end_ms=900, confidence=0.9,
            ),
            TranscriptResult(
                text="  ", speaker=None, is_final=True,
                start_ms=900, end_ms=1000, confidence=0.9,
            ),
            TranscriptResult(
                text="there", speaker=None, is_final=True,
                start_ms=1000, end_ms=1800, confidence=0.9,
            ),
        ]

    monkeypatch.setattr(source_fetch, "_download_youtube_audio", fake_download)
    with patch("app.core.transcription.transcribe_audio_file", side_effect=fake_stt):
        text, language, segments = await source_fetch._transcribe_youtube_audio(
            "https://youtu.be/abc", "abc", "u1"
        )
    assert text == "hello there"
    assert language is None
    assert segments == [
        {"content": "hello", "start_ms": 0, "end_ms": 900},
        {"content": "there", "start_ms": 1000, "end_ms": 1800},
    ]


@pytest.mark.asyncio
async def test_transcribe_youtube_audio_no_speech_raises(monkeypatch) -> None:
    def fake_download(url):
        return b"a", "audio/mp4", 1.0

    async def fake_stt(data, **kwargs):
        return []

    monkeypatch.setattr(source_fetch, "_download_youtube_audio", fake_download)
    with patch("app.core.transcription.transcribe_audio_file", side_effect=fake_stt):
        with pytest.raises(SourceFetchError) as ei:
            await source_fetch._transcribe_youtube_audio(
                "https://youtu.be/abc", "abc", "u1"
            )
    assert ei.value.code == "youtube_audio_no_speech"


def test_download_youtube_audio_happy_path(tmp_path, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            out = self.opts["outtmpl"].replace("%(ext)s", "m4a")
            from pathlib import Path

            Path(out).write_bytes(b"fake-m4a")
            return {"duration": 33}

    class FakeDownloadError(Exception):
        pass

    fake_mod = SimpleNamespace(
        YoutubeDL=FakeYDL, utils=SimpleNamespace(DownloadError=FakeDownloadError)
    )
    with patch.dict(sys.modules, {"yt_dlp": fake_mod, "yt_dlp.utils": fake_mod.utils}):
        data, content_type, duration = source_fetch._download_youtube_audio(
            "https://youtu.be/abc"
        )
    assert data == b"fake-m4a"
    assert content_type == "audio/mp4"
    assert duration == 33.0


def test_download_youtube_audio_failure_raises(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    class FakeDownloadError(Exception):
        pass

    class FailingYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            raise FakeDownloadError("nope")

    fake_mod = SimpleNamespace(
        YoutubeDL=FailingYDL, utils=SimpleNamespace(DownloadError=FakeDownloadError)
    )
    with patch.dict(sys.modules, {"yt_dlp": fake_mod, "yt_dlp.utils": fake_mod.utils}):
        with pytest.raises(SourceFetchError) as ei:
            source_fetch._download_youtube_audio("https://youtu.be/abc")
    assert ei.value.code == "youtube_audio_download_failed"


def test_download_youtube_audio_filtered_out_raises(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    class SkippingYDL:
        """Simulates yt-dlp skipping the download (too long / too large)."""

        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            return {"duration": 99999}  # filtered: no file written

    fake_mod = SimpleNamespace(
        YoutubeDL=SkippingYDL,
        utils=SimpleNamespace(DownloadError=type("E", (Exception,), {})),
    )
    with patch.dict(sys.modules, {"yt_dlp": fake_mod, "yt_dlp.utils": fake_mod.utils}):
        with pytest.raises(SourceFetchError) as ei:
            source_fetch._download_youtube_audio("https://youtu.be/abc")
    assert ei.value.code == "youtube_audio_too_large"
