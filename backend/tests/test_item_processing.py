"""DB-backed tests for the item processing pipeline (fetch -> embed -> summarize)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import item_processing
from app.core.item_ingest import ingest_item
from app.core.item_processing import process_item
from app.core.source_fetch import FetchedContent, SourceFetchError
from app.core.summarizer import KeyMoment, SummaryResult
from app.models.item import ItemChunk, ItemSummary
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"proc-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _fake_embedder(texts: list[str]) -> list[list[float]]:
    return [[0.02] * 1536 for _ in texts]


def _fake_summary() -> SummaryResult:
    return SummaryResult(
        title="Fetched Title",
        summary="summary",
        key_points=["kp"],
        decisions=[],
        action_items=[],
        topics=[],
        people_mentioned=[],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=[],
    )


def _patch_summary(monkeypatch) -> None:
    async def fake_summarize(text, **kwargs):
        return _fake_summary()

    async def fake_moments(text, **kwargs):
        return [
            KeyMoment(
                timestamp="00:10", moment="m", why_it_matters="w",
                quote=None, importance="high",
            )
        ]

    monkeypatch.setattr(item_processing, "generate_item_summary", _real_generate)
    # Patch the summarizer functions used deep in generate_item_summary.
    from app.core import item_summary

    monkeypatch.setattr(item_summary, "summarize_content", fake_summarize)
    monkeypatch.setattr(item_summary, "extract_key_moments", fake_moments)


# Use the real generate_item_summary but with patched LLM calls underneath.
from app.core.item_summary import generate_item_summary as _real_generate  # noqa: E402


async def test_process_url_item_fetches_then_summarizes(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    url = "https://example.com/article"
    item, _ = await ingest_item(
        db_session, user.id, source="url", kind="article", url=url,
        dedup_key=url, body=None, embed=False,
    )
    assert item.body is None

    async def fake_fetch(u: str) -> FetchedContent:
        assert u == url
        return FetchedContent(
            source_type="article", kind="article", url=u,
            title="Real Title", body="The fetched article body about energy.",
            metadata={"author": "X"},
        )

    _patch_summary(monkeypatch)
    await process_item(
        db_session, item, fetcher=fake_fetch, embedder=_fake_embedder
    )

    assert item.body == "The fetched article body about energy."
    assert item.title == "Real Title"
    assert item.metadata_["author"] == "X"
    # Chunks embedded.
    chunks = (
        (await db_session.execute(select(ItemChunk).where(ItemChunk.item_id == item.id)))
        .scalars().all()
    )
    assert len(chunks) >= 1
    assert all(c.embedding is not None for c in chunks)
    # Summary row created.
    summary = (
        await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    assert summary is not None
    assert summary.key_moments[0]["moment"] == "m"


async def test_process_fetch_error_marks_needs_input(db_session) -> None:
    user = await _make_user(db_session)
    url = "https://www.instagram.com/reel/abc/"
    item, _ = await ingest_item(
        db_session, user.id, source="url", kind="post", url=url,
        dedup_key=url, body=None, embed=False,
    )

    async def fake_fetch(u: str) -> FetchedContent:
        raise SourceFetchError("Share the file", code="instagram_share_required")

    result = await process_item(
        db_session, item, fetcher=fake_fetch, embedder=_fake_embedder
    )
    assert result.state == "needs_input"
    assert result.metadata_["fetch_error"]["code"] == "instagram_share_required"
    assert "Share the file" in result.metadata_["fetch_error"]["message"]
    # No summary created.
    summary = (
        await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    assert summary is None


async def test_process_body_item_skips_fetch(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="paste", title="T",
        body="already has a body of text", embedder=_fake_embedder,
    )

    async def fail_fetch(u: str):
        raise AssertionError("should not fetch when body present")

    _patch_summary(monkeypatch)
    await process_item(
        db_session, item, fetcher=fail_fetch, embedder=_fake_embedder
    )
    summary = (
        await db_session.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    assert summary is not None
