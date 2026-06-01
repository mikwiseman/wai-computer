"""Unit tests for source fetchers (URL classification + dispatch + errors).

Network/library seams are patched so these run offline.
"""

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
async def test_youtube_fetches_transcript() -> None:
    with patch.object(
        source_fetch, "_fetch_youtube_transcript", return_value=("hello world transcript", "en")
    ):
        content = await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert content.source_type == "youtube"
    assert content.kind == "video"
    assert content.body == "hello world transcript"
    assert content.metadata["video_id"] == "dQw4w9WgXcQ"
    assert content.metadata["language"] == "en"


@pytest.mark.asyncio
async def test_youtube_no_transcript_propagates_friendly_error() -> None:
    def _boom(_vid):
        raise SourceFetchError("no transcript", code="youtube_no_transcript")

    with patch.object(source_fetch, "_fetch_youtube_transcript", side_effect=_boom):
        with pytest.raises(SourceFetchError) as ei:
            await fetch_url("https://youtu.be/dQw4w9WgXcQ")
    assert ei.value.code == "youtube_no_transcript"


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
