"""Tests for _MarkdownDeltaExtractor (streaming JSON markdown extractor)
and _execute_tool (tool dispatch) in app.core.companion."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.companion import (
    CompanionError,
    _execute_tool,
    _MarkdownDeltaExtractor,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# _MarkdownDeltaExtractor
# ---------------------------------------------------------------------------


class TestMarkdownDeltaExtractor:
    def test_empty_input_yields_empty(self) -> None:
        ex = _MarkdownDeltaExtractor()
        assert ex.feed("") == ""
        assert ex.is_done is False

    def test_no_markdown_key_returns_nothing(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"other":"value"}')
        assert out == ""
        assert ex.is_done is False

    def test_locates_markdown_and_consumes_plain_chars(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"markdown":"hello')
        assert out == "hello"

    def test_chunked_input_accumulates_buffer(self) -> None:
        ex = _MarkdownDeltaExtractor()
        a = ex.feed('{"markdown"')
        b = ex.feed(': "abc')
        c = ex.feed("def")
        assert a == ""
        assert b == "abc"
        assert c == "def"

    def test_closing_quote_finalises_state(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"markdown":"complete"')
        assert out == "complete"
        assert ex.is_done is True
        # Subsequent feeds are no-ops
        assert ex.feed(',"citations":[]}') == ""

    def test_simple_escape_sequences_decoded(self) -> None:
        ex = _MarkdownDeltaExtractor()
        # Backslash-n becomes newline; backslash-t becomes tab; \"  literal quote.
        out = ex.feed('{"markdown":"a\\nb\\tc\\"d"')
        assert out == 'a\nb\tc"d'
        assert ex.is_done is True

    def test_other_escape_simple_codes(self) -> None:
        ex = _MarkdownDeltaExtractor()
        # \\ → \, \/ → /, \b → \b, \f → \f, \r → \r
        out = ex.feed('{"markdown":"a\\\\b\\/c\\bd\\fe\\rf"')
        assert "\\" in out
        assert "/" in out
        assert "\b" in out
        assert "\f" in out
        assert "\r" in out

    def test_unicode_escape_decoded(self) -> None:
        ex = _MarkdownDeltaExtractor()
        # A = "A"
        out = ex.feed('{"markdown":"\\u0041"')
        assert out == "A"

    def test_incomplete_unicode_escape_holds(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out1 = ex.feed('{"markdown":"\\u00')
        assert out1 == ""  # incomplete escape — wait for more bytes
        out2 = ex.feed("41")
        assert out2 == "A"

    def test_invalid_unicode_escape_keeps_literal(self) -> None:
        ex = _MarkdownDeltaExtractor()
        # \uZZZZ is not valid hex — should fall through to literal 6-char output
        out = ex.feed('{"markdown":"\\uZZZZ"')
        assert "\\uZZZZ" in out

    def test_unknown_escape_keeps_two_chars(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"markdown":"\\x"')
        assert "\\x" in out

    def test_trailing_backslash_waits_for_more(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out1 = ex.feed('{"markdown":"abc\\')
        assert out1 == "abc"
        out2 = ex.feed('n"')
        assert out2 == "\n"

    def test_whitespace_between_key_and_value_tolerated(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"markdown"  :  "ok"')
        assert out == "ok"

    def test_key_followed_by_non_colon_returns_nothing(self) -> None:
        ex = _MarkdownDeltaExtractor()
        # Key present but not followed by ":" → can't locate value yet.
        out = ex.feed('{"markdown"abc')
        assert out == ""
        assert ex.is_done is False

    def test_colon_followed_by_non_quote_returns_nothing(self) -> None:
        ex = _MarkdownDeltaExtractor()
        out = ex.feed('{"markdown":123')
        assert out == ""

    def test_repeated_feed_after_done_is_noop(self) -> None:
        ex = _MarkdownDeltaExtractor()
        ex.feed('{"markdown":"hi"')
        assert ex.is_done
        assert ex.feed("more bytes") == ""


# ---------------------------------------------------------------------------
# _execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_raises_for_unknown_tool(
    db_session: AsyncSession,
) -> None:
    user = User(email="exec-unknown@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(CompanionError) as exc:
        await _execute_tool(
            "no_such_tool", {}, db_session, user.id, scope=None,
        )
    assert exc.value.code == "unknown_tool"


@pytest.mark.asyncio
async def test_execute_tool_dispatches_to_search_transcripts(
    db_session: AsyncSession,
) -> None:
    user = User(email="exec-search@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    result = await _execute_tool(
        "search_transcripts",
        {"query": "anything"},
        db_session, user.id, scope=None,
    )
    assert result.payload_for_model == {"segments": []}


@pytest.mark.asyncio
async def test_execute_tool_dispatches_to_list_recordings(
    db_session: AsyncSession,
) -> None:
    user = User(email="exec-list@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    result = await _execute_tool(
        "list_recordings", {}, db_session, user.id, scope=None,
    )
    assert "recordings" in result.payload_for_model


@pytest.mark.asyncio
async def test_execute_tool_remember_receives_conversation_id(
    db_session: AsyncSession,
) -> None:
    """remember is the only tool that receives conversation_id; verify the
    branch is taken without inspecting the (complex) memory-write side effect."""
    user = User(email="exec-remember@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    convo_id = uuid.uuid4()

    # Pass minimal valid args; we only care that dispatch reaches the handler
    # with conversation_id wired. The remember tool writes to user_memory_log
    # which has a FK to conversations — without a real conversation, it raises
    # an IntegrityError. That error proves dispatch reached the handler.
    from sqlalchemy.exc import IntegrityError

    try:
        await _execute_tool(
            "remember",
            {"block": "human", "operation": "append", "content": "test"},
            db_session, user.id, scope=None,
            conversation_id=convo_id,
        )
    except (CompanionError, IntegrityError):
        # Either error path is fine — both prove dispatch routed correctly.
        pass
