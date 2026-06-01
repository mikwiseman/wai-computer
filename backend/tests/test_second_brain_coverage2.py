"""Second pass of targeted coverage for second-brain wrappers + DB paths.

Closes the remaining uncovered lines flagged by the coverage report:
source_fetch I/O + error paths, comparison_build summary/failure paths,
content hard-split + doc-embed edge, mcp_sync inner skip, route error paths.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# --- content.py: oversized-paragraph hard split + helper -------------------


def test_chunk_hard_splits_oversized_paragraph() -> None:
    from app.core.content import chunk_with_header

    huge = "word " * 1000  # one paragraph far over max_chars
    chunks = chunk_with_header("T", huge, max_chars=200, overlap_chars=20)
    assert len(chunks) > 1
    for c in chunks:
        assert c.startswith("T › ")
        assert len(c) <= 200 + len("T › ") + 5


def test_hard_split_overlaps() -> None:
    from app.core.content import _hard_split

    parts = _hard_split("abcdefghij", 4, 1)
    assert parts[0] == "abcd"
    # step = 4 - 1 = 3 -> next starts at index 3
    assert parts[1].startswith("d")


# --- source_fetch.py: _http_get, pdf extract, youtube error paths ----------


@pytest.mark.asyncio
async def test_http_get_returns_bytes_and_content_type() -> None:
    from app.core import source_fetch as sf

    fake_resp = SimpleNamespace(
        content=b"<html>hi</html>",
        headers={"content-type": "text/html; charset=utf-8"},
        raise_for_status=lambda: None,
    )

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return fake_resp

    with patch.dict("sys.modules", {"httpx": SimpleNamespace(AsyncClient=FakeClient)}):
        body, ctype = await sf._http_get("https://x/post")
    assert body == b"<html>hi</html>"
    assert "text/html" in ctype


def test_extract_pdf_text_joins_pages() -> None:
    from app.core import source_fetch as sf

    class FakePage:
        def __init__(self, t):
            self._t = t

        def extract_text(self):
            return self._t

    class FakePdf:
        pages = [FakePage("page one"), FakePage(""), FakePage("page three")]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_pdfplumber = SimpleNamespace(open=lambda buf: FakePdf())
    with patch.dict("sys.modules", {"pdfplumber": fake_pdfplumber}):
        text = sf._extract_pdf_text(b"%PDF-1.7")
    assert "page one" in text
    assert "page three" in text


def test_fetch_youtube_transcript_no_transcript_raises() -> None:
    from app.core import source_fetch as sf

    class CouldNotRetrieveError(Exception):
        pass

    class UnavailableError(Exception):
        pass

    def _raise(vid):
        raise CouldNotRetrieveError("none")

    fake_api = SimpleNamespace(fetch=_raise)
    fake_mod = SimpleNamespace(YouTubeTranscriptApi=lambda: fake_api)
    fake_errors = SimpleNamespace(
        CouldNotRetrieveTranscript=CouldNotRetrieveError, VideoUnavailable=UnavailableError
    )
    with patch.dict(
        "sys.modules",
        {"youtube_transcript_api": fake_mod, "youtube_transcript_api._errors": fake_errors},
    ):
        with pytest.raises(sf.SourceFetchError) as ei:
            sf._fetch_youtube_transcript("vid")
    assert ei.value.code == "youtube_no_transcript"


def test_fetch_youtube_transcript_generic_error_raises() -> None:
    from app.core import source_fetch as sf

    def _raise(vid):
        raise RuntimeError("network")

    fake_api = SimpleNamespace(fetch=_raise)
    fake_mod = SimpleNamespace(YouTubeTranscriptApi=lambda: fake_api)
    fake_errors = SimpleNamespace(
        CouldNotRetrieveTranscript=type("E1", (Exception,), {}),
        VideoUnavailable=type("E2", (Exception,), {}),
    )
    with patch.dict(
        "sys.modules",
        {"youtube_transcript_api": fake_mod, "youtube_transcript_api._errors": fake_errors},
    ):
        with pytest.raises(sf.SourceFetchError) as ei:
            sf._fetch_youtube_transcript("vid")
    assert ei.value.code == "youtube_fetch_failed"


def test_fetch_youtube_transcript_empty_raises() -> None:
    from app.core import source_fetch as sf

    class FetchedList(list):
        language_code = "en"

    fake_api = SimpleNamespace(fetch=lambda vid: FetchedList([SimpleNamespace(text="  ")]))
    fake_mod = SimpleNamespace(YouTubeTranscriptApi=lambda: fake_api)
    fake_errors = SimpleNamespace(
        CouldNotRetrieveTranscript=type("E1", (Exception,), {}),
        VideoUnavailable=type("E2", (Exception,), {}),
    )
    with patch.dict(
        "sys.modules",
        {"youtube_transcript_api": fake_mod, "youtube_transcript_api._errors": fake_errors},
    ):
        with pytest.raises(sf.SourceFetchError) as ei:
            sf._fetch_youtube_transcript("vid")
    assert ei.value.code == "youtube_empty"


@pytest.mark.asyncio
async def test_fetch_youtube_bad_url_raises() -> None:
    from app.core import source_fetch as sf

    with pytest.raises(sf.SourceFetchError) as ei:
        await sf._fetch_youtube("https://youtube.com/watch?novideo=1")
    assert ei.value.code == "youtube_bad_url"


def test_extract_article_metadata_failure_tolerated() -> None:
    from app.core import source_fetch as sf

    def _boom_meta(html):
        raise RuntimeError("meta parse failed")

    fake_traf = SimpleNamespace(
        extract=lambda html, **k: "body text", extract_metadata=_boom_meta
    )
    with patch.dict("sys.modules", {"trafilatura": fake_traf}):
        title, body = sf._extract_article("<html/>", "https://x")
    assert title is None
    assert body == "body text"


# --- comparison_build.py: summary-text path + build-failure path -----------


@pytest.mark.asyncio
async def test_comparison_build_summary_text_and_failure(db_session, monkeypatch) -> None:
    from app.core import comparison_build as cb
    from app.core.comparison import ComparisonError
    from app.core.item_ingest import ingest_item
    from app.models.comparison import ComparisonSet
    from app.models.item import ItemSummary
    from app.models.user import User

    async def _emb(texts):
        return [[0.01] * 1536 for _ in texts]

    user = User(email=f"cb-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    ids = []
    for i in range(2):
        item, _ = await ingest_item(
            db_session, user.id, source="paste", title=f"I{i}", body=f"body {i}", embedder=_emb
        )
        # Attach a summary so _item_text takes the summary branch (lines 21-23).
        db_session.add(
            ItemSummary(item_id=item.id, summary=f"sum {i}", key_points=["k1", "k2"])
        )
        ids.append(str(item.id))
    await db_session.flush()

    cs = ComparisonSet(user_id=user.id, item_ids=ids, status="generating")
    db_session.add(cs)
    await db_session.flush()

    # Force build_comparison to fail -> status=failed branch (lines 68-73).
    async def _boom(items, **kw):
        raise ComparisonError("induction failed")

    monkeypatch.setattr(cb, "build_comparison", _boom)
    with pytest.raises(ComparisonError):
        await cb.build_comparison_set(db_session, cs.id, intent="x")
    assert cs.status == "failed"
    assert "Comparison failed" in (cs.schema_rationale or "")


@pytest.mark.asyncio
async def test_comparison_build_missing_set_returns_none(db_session) -> None:
    from app.core import comparison_build as cb

    assert await cb.build_comparison_set(db_session, uuid4()) is None


# --- mcp_sync inner: missing connection short-circuits ---------------------


@pytest.mark.asyncio
async def test_mcp_sync_inner_missing_connection(db_session, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.tasks import mcp_sync

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(mcp_sync, "get_db_context", ctx)
    with patch.object(mcp_sync, "sync_connection", AsyncMock()) as sc:
        await mcp_sync._sync_one(str(uuid4()))
    sc.assert_not_called()
