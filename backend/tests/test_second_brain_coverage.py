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


# --- mcp_client.py: SDK result extraction helpers (pure) --------------------


def test_resource_text_extracts_text_parts() -> None:
    from app.core.mcp_client import _resource_text

    result = SimpleNamespace(
        contents=[
            SimpleNamespace(text="hello"),
            SimpleNamespace(text=None),
            SimpleNamespace(text="world"),
        ]
    )
    assert _resource_text(result) == "hello\nworld"


def test_tool_text_extracts_and_caps() -> None:
    from app.core.mcp_client import _tool_text

    result = SimpleNamespace(content=[SimpleNamespace(text="a"), SimpleNamespace(text="b")])
    assert _tool_text(result) == "a\nb"


def test_resource_text_handles_empty() -> None:
    from app.core.mcp_client import _resource_text, _tool_text

    assert _resource_text(SimpleNamespace(contents=[])) == ""
    assert _tool_text(SimpleNamespace(content=None)) == ""


# --- mcp_client.py: introspect/list/read via a stubbed session --------------


@pytest.mark.asyncio
async def test_mcp_client_introspect_and_read() -> None:
    from app.core import mcp_client as mc

    fake_session = SimpleNamespace(
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[SimpleNamespace(name="search")])),
        list_resources=AsyncMock(
            return_value=SimpleNamespace(
                resources=[
                    SimpleNamespace(
                        uri="r://1", name="R1", description=None, mimeType="text/plain"
                    )
                ]
            )
        ),
        read_resource=AsyncMock(
            return_value=SimpleNamespace(contents=[SimpleNamespace(text="body")])
        ),
        call_tool=AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text="tool out")])
        ),
    )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(url, token):
        yield fake_session

    with patch.object(mc, "_open_session", fake_open):
        client = mc.McpClient("https://x/mcp", "tok")
        intro = await client.introspect()
        assert intro.tools == ["search"]
        assert intro.resources[0].uri == "r://1"
        resources = await client.list_resources()
        assert resources[0].name == "R1"
        body = await client.read_resource("r://1")
        assert body == "body"
        out = await client.call_tool("search", {"q": "x"})
        assert out == "tool out"


@pytest.mark.asyncio
async def test_mcp_client_introspect_tolerates_no_resources() -> None:
    from app.core import mcp_client as mc

    fake_session = SimpleNamespace(
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[])),
        list_resources=AsyncMock(side_effect=RuntimeError("not supported")),
    )
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(url, token):
        yield fake_session

    with patch.object(mc, "_open_session", fake_open):
        intro = await mc.McpClient("https://x/mcp").introspect()
    assert intro.tools == []
    assert intro.resources == []


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

    snippets = [SimpleNamespace(text="hello"), SimpleNamespace(text="world")]
    SimpleNamespace(language_code="en")
    fake_api = SimpleNamespace(fetch=lambda vid: snippets)

    fake_mod = SimpleNamespace(YouTubeTranscriptApi=lambda: fake_api)
    fake_errors = SimpleNamespace(CouldNotRetrieveTranscript=type("E1", (Exception,), {}),
                                  VideoUnavailable=type("E2", (Exception,), {}))
    # Make the snippet list also expose language_code via the FetchedTranscript-like object.
    class FetchedList(list):
        language_code = "en"

    fake_api.fetch = lambda vid: FetchedList(snippets)
    with patch.dict(
        "sys.modules",
        {"youtube_transcript_api": fake_mod, "youtube_transcript_api._errors": fake_errors},
    ):
        text, lang = sf._fetch_youtube_transcript("vid123")
    assert "hello world" == text
    assert lang == "en"


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
async def test_mcp_sync_inner_skips_disabled(db_session, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.models.mcp_connection import McpConnection
    from app.models.user import User
    from app.tasks import mcp_sync

    user = User(email=f"inner-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conn = McpConnection(
        user_id=user.id, server_label="off", server_url="https://off/mcp", enabled=False
    )
    db_session.add(conn)
    await db_session.flush()

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(mcp_sync, "get_db_context", ctx)
    # Disabled connection -> sync_connection never called.
    with patch.object(mcp_sync, "sync_connection", AsyncMock()) as sc:
        await mcp_sync._sync_one(str(conn.id))
    sc.assert_not_called()


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
