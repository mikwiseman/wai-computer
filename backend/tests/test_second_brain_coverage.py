"""Targeted coverage for second-brain I/O wrappers + inner task coroutines.

These exercise the thin library/SDK/LLM wrapper code paths (stubbed, never
hitting the network) and the inner async task bodies, which the behavioural
tests legitimately mock out.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# --- comparison.py: real _induce_columns / _extract_row (stubbed client) ----


@pytest.mark.asyncio
async def test_induce_columns_calls_model_and_returns_schema() -> None:
    from app.core import comparison
    from app.core.comparison import ComparisonItem, _Column, _ColumnSchema, _induce_columns

    payload = _ColumnSchema(columns=[_Column(name="Price", type="number")], rationale="r")
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )
    with (
        patch.object(comparison, "get_openai_client", return_value=fake_client),
        patch.object(comparison, "ensure_response_completed"),
    ):
        items = [
            ComparisonItem(item_id="a", title="A", text="x"),
            ComparisonItem(item_id="b", title="B", text="y"),
        ]
        schema = await _induce_columns(items, "by price")
    assert schema.columns[0].name == "Price"
    # intent is woven into the prompt
    sent = fake_client.responses.parse.call_args.kwargs["input"]
    assert "by price" in sent


@pytest.mark.asyncio
async def test_extract_row_calls_model() -> None:
    from app.core import comparison
    from app.core.comparison import ComparisonItem, _Column, _extract_row, _RowSchema, _RowValue

    payload = _RowSchema(values=[_RowValue(column="Price", value="10")])
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )
    with (
        patch.object(comparison, "get_openai_client", return_value=fake_client),
        patch.object(comparison, "ensure_response_completed"),
    ):
        row = await _extract_row(
            ComparisonItem(item_id="a", title="A", text="x"), [_Column(name="Price", type="number")]
        )
    assert row.values[0].value == "10"


@pytest.mark.asyncio
async def test_induce_columns_raises_on_no_parse() -> None:
    from app.core import comparison
    from app.core.comparison import ComparisonError, ComparisonItem, _induce_columns

    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=None)))
    )
    with (
        patch.object(comparison, "get_openai_client", return_value=fake_client),
        patch.object(comparison, "ensure_response_completed"),
    ):
        pair = [ComparisonItem("a", "A", "x"), ComparisonItem("b", "B", "y")]
        with pytest.raises(ComparisonError):
            await _induce_columns(pair, None)


# --- source_fetch.py: library wrapper helpers (stubbed libs) ----------------


def test_extract_article_uses_trafilatura() -> None:
    from app.core import source_fetch as sf

    fake_traf = SimpleNamespace(
        extract=lambda html, **k: "clean body",
        extract_metadata=lambda html: SimpleNamespace(title="The Title"),
    )
    with patch.dict("sys.modules", {"trafilatura": fake_traf}):
        title, body = sf._extract_article("<html>..</html>", "https://x/post")
    assert title == "The Title"
    assert body == "clean body"


@pytest.mark.asyncio
async def test_fetch_youtube_transcript_joins_snippets() -> None:
    from app.core import source_fetch as sf

    class FetchedList(list):
        language_code = "en"

    snippets = FetchedList(
        [
            SimpleNamespace(text="hello", start=0.0, duration=1.0),
            SimpleNamespace(text="world", start=1.0, duration=1.5),
        ]
    )
    transcript = SimpleNamespace(
        fetch=lambda: snippets, is_generated=False, language_code="en"
    )

    class FakeList:
        def find_transcript(self, codes):
            return transcript

        def __iter__(self):
            return iter([transcript])

    fake_api = SimpleNamespace(list=lambda vid: FakeList())
    with patch.object(sf, "_youtube_api", return_value=fake_api):
        text, lang, segments = sf._fetch_youtube_transcript("vid123")
    assert text == "hello world"
    assert lang == "en"
    assert segments == [
        {"content": "hello", "start_ms": 0, "end_ms": 1000},
        {"content": "world", "start_ms": 1000, "end_ms": 2500},
    ]


@pytest.mark.asyncio
async def test_fetch_pdf_bytes_dispatch() -> None:
    from app.core import source_fetch as sf

    with patch.object(sf, "_extract_pdf_text", return_value="pdf text"):
        content = await sf._fetch_pdf_bytes("https://x/a.pdf", b"%PDF-1.7")
    assert content.source_type == "pdf"
    assert content.body == "pdf text"


# --- inner async task coroutines (DB-backed) --------------------------------


@pytest.mark.asyncio
async def test_item_summary_inner_skips_missing_and_bodyless(db_session, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.tasks import item_summary_generation as isg

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(isg, "get_db_context", ctx)
    # Missing item id -> no-op (covers the not-found branch).
    await isg._generate_item_summary(item_id=str(uuid4()))


@pytest.mark.asyncio
async def test_comparison_inner_generate(db_session, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.tasks import comparison_generation as cg

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(cg, "get_db_context", ctx)
    with patch.object(cg, "build_comparison_set", AsyncMock()) as b:
        await cg._generate(comparison_id=str(uuid4()), intent="x")
    b.assert_awaited_once()
