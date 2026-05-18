"""Unit tests for app.core.mcp_tools — both the pure helpers and the DB-coupled
search/fetch entry points used by the MCP server."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mcp_tools
from app.core.mcp_tools import (
    fetch_recording_for_mcp,
    search_recordings_for_mcp,
)
from app.models.recording import ActionItem, Recording, Segment, Summary
from app.models.user import User


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_as_uuid_accepts_uuid_instance() -> None:
    uid = uuid4()
    assert mcp_tools._as_uuid(uid) is uid


def test_as_uuid_parses_string() -> None:
    uid = uuid4()
    assert mcp_tools._as_uuid(str(uid)) == uid


def test_recording_url_uses_frontend_setting() -> None:
    uid = uuid4()
    url = mcp_tools._recording_url(uid)
    assert url.endswith(f"/dashboard?recording={uid}")
    assert "://" in url, "url must include scheme from settings.frontend_url"


def test_iso_returns_none_when_value_is_none() -> None:
    assert mcp_tools._iso(None) is None


def test_iso_serialises_datetime() -> None:
    dt = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
    assert mcp_tools._iso(dt) == dt.isoformat()


def test_first_match_snippet_short_text_returned_verbatim() -> None:
    short = "hello world"
    snippet = mcp_tools._first_match_snippet(short, "world", max_chars=500)
    assert snippet == "hello world"


def test_first_match_snippet_collapses_whitespace() -> None:
    text = "alpha   beta\n\n\nfoo   bar"
    snippet = mcp_tools._first_match_snippet(text, "alpha")
    assert snippet == "alpha beta foo bar"


def test_first_match_snippet_long_text_no_match_truncates_from_start() -> None:
    text = " ".join(["word"] * 200)  # ~999 chars
    snippet = mcp_tools._first_match_snippet(text, "missing", max_chars=80)
    assert snippet.endswith("...")
    # Source: `clean[: max_chars - 1].rstrip() + "..."` → up to (max_chars - 1) + 3
    assert len(snippet) <= 82


def test_first_match_snippet_long_text_with_match_centres_window() -> None:
    prefix = " ".join(["foo"] * 200)
    suffix = " ".join(["bar"] * 200)
    text = f"{prefix} TARGET {suffix}"
    snippet = mcp_tools._first_match_snippet(text, "TARGET", max_chars=120)
    assert "TARGET" in snippet
    assert snippet.startswith("..."), "ellipsis prepended when window starts mid-string"
    assert snippet.endswith("...")
    # Window is up to max_chars chars + leading "..." (3) + trailing "..." (3)
    assert len(snippet) <= 127


def test_first_match_snippet_handles_query_at_start() -> None:
    text = "TARGET " + " ".join(["x"] * 500)
    snippet = mcp_tools._first_match_snippet(text, "TARGET", max_chars=80)
    assert snippet.startswith("TARGET")
    # snippet may end with "..."
    assert snippet.endswith("...")


def test_summary_metadata_returns_empty_when_summary_none() -> None:
    assert mcp_tools._summary_metadata(None) == {}


def test_summary_metadata_pulls_lists_and_sentiment() -> None:
    summary = Summary(
        recording_id=uuid4(),
        summary="text",
        key_points=["a"],
        topics=["t1", "t2"],
        people_mentioned=["alice"],
        sentiment="neutral",
    )
    meta = mcp_tools._summary_metadata(summary)
    assert meta == {
        "topics": ["t1", "t2"],
        "people_mentioned": ["alice"],
        "sentiment": "neutral",
    }


def test_summary_metadata_defaults_empty_lists_when_null() -> None:
    summary = Summary(recording_id=uuid4(), summary=None)
    # topics/people_mentioned default to [] via `or []`
    meta = mcp_tools._summary_metadata(summary)
    assert meta["topics"] == []
    assert meta["people_mentioned"] == []
    assert meta["sentiment"] is None


def test_format_transcript_sorts_and_handles_missing_speaker() -> None:
    rid = uuid4()
    segs = [
        Segment(recording_id=rid, speaker="Alice", content="second", start_ms=2000),
        Segment(recording_id=rid, speaker=None, content="first", start_ms=1000),
        Segment(recording_id=rid, speaker="Bob", content="third", start_ms=3000),
    ]
    out = mcp_tools._format_transcript(segs)
    assert out == "Unknown: first\nAlice: second\nBob: third"


def test_format_action_items_includes_owner_and_due_date() -> None:
    rid = uuid4()
    items = [
        ActionItem(recording_id=rid, task="task A", owner="Alice",
                   due_date=date(2026, 5, 25)),
        ActionItem(recording_id=rid, task="task B"),  # no owner, no due
        ActionItem(recording_id=rid, task="task C", owner="Charlie"),
    ]
    out = mcp_tools._format_action_items(items)
    assert "- task A (Alice) due 2026-05-25" in out
    assert "- task B" in out
    assert "- task C (Charlie)" in out


def test_format_action_items_empty_list_returns_empty_string() -> None:
    assert mcp_tools._format_action_items([]) == ""


def test_truncate_text_within_limit_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass settings dependency by setting a small cap
    short = "hello"
    text, truncated = mcp_tools._truncate_text(short)
    assert text == short
    assert truncated is False


def test_truncate_text_exceeds_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch get_settings inside the mcp_tools module to a minimal stand-in.
    from types import SimpleNamespace

    monkeypatch.setattr(
        mcp_tools,
        "get_settings",
        lambda: SimpleNamespace(mcp_max_tool_text_chars=10),
    )
    text, truncated = mcp_tools._truncate_text("0123456789ABCDEFGHIJ")
    assert truncated is True
    assert text.endswith("...")
    assert len(text) <= 12  # max_chars - 1 + "..." after rstrip


# ---------------------------------------------------------------------------
# DB-coupled: search_recordings_for_mcp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_empty_for_blank_query(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-blank@example.com")
    result = await search_recordings_for_mcp(db_session, user.id, "   ", limit=10)
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_search_returns_empty_for_empty_query(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-empty@example.com")
    result = await search_recordings_for_mcp(db_session, user.id, "", limit=10)
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_search_rejects_invalid_limit_low(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-limit-low@example.com")
    with pytest.raises(ValueError, match="limit must be between"):
        await search_recordings_for_mcp(db_session, user.id, "q", limit=0)


@pytest.mark.asyncio
async def test_search_rejects_invalid_limit_high(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-limit-high@example.com")
    with pytest.raises(ValueError, match="limit must be between"):
        await search_recordings_for_mcp(db_session, user.id, "q", limit=10_000)


@pytest.mark.asyncio
async def test_search_matches_title(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-title@example.com")
    rec = await _create_recording(db_session, user.id, title="Quarterly Planning")
    await db_session.commit()

    out = await search_recordings_for_mcp(db_session, user.id, "Quarterly", limit=5)
    ids = {r["id"] for r in out["results"]}
    assert str(rec.id) in ids
    assert any("Quarterly" in r["title"] for r in out["results"])


@pytest.mark.asyncio
async def test_search_matches_segment_content(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-seg@example.com")
    rec = await _create_recording(db_session, user.id, title="Untitled")
    seg = Segment(
        recording_id=rec.id, speaker="Alice",
        content="We discussed the WIDGET roadmap thoroughly", start_ms=0,
    )
    db_session.add(seg)
    await db_session.commit()

    out = await search_recordings_for_mcp(db_session, user.id, "WIDGET", limit=5)
    assert len(out["results"]) >= 1
    found = next(r for r in out["results"] if r["id"] == str(rec.id))
    assert "WIDGET" in found["text"]
    assert found["url"].endswith(f"/dashboard?recording={rec.id}")


@pytest.mark.asyncio
async def test_search_uses_default_title_when_missing(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-untitled@example.com")
    rec = await _create_recording(db_session, user.id, title=None)
    seg = Segment(
        recording_id=rec.id, speaker="Bob",
        content="hello world UNIQUEMARK matches", start_ms=0,
    )
    db_session.add(seg)
    await db_session.commit()

    out = await search_recordings_for_mcp(db_session, user.id, "UNIQUEMARK", limit=5)
    found = next(r for r in out["results"] if r["id"] == str(rec.id))
    assert found["title"] == "Untitled Recording"


@pytest.mark.asyncio
async def test_search_skips_deleted_recordings(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "search-deleted@example.com")
    rec = await _create_recording(db_session, user.id, title="DELETED_TARGET")
    rec.deleted_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    await db_session.commit()

    out = await search_recordings_for_mcp(db_session, user.id, "DELETED_TARGET", limit=5)
    assert out["results"] == []


@pytest.mark.asyncio
async def test_search_respects_user_isolation(db_session: AsyncSession) -> None:
    user_a = await _create_user(db_session, "search-iso-a@example.com")
    user_b = await _create_user(db_session, "search-iso-b@example.com")
    await _create_recording(db_session, user_b.id, title="USERB_ONLY")
    await db_session.commit()

    out = await search_recordings_for_mcp(db_session, user_a.id, "USERB_ONLY", limit=5)
    assert out["results"] == []


# ---------------------------------------------------------------------------
# DB-coupled: fetch_recording_for_mcp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_missing_recording_returns_none(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "fetch-miss@example.com")
    out = await fetch_recording_for_mcp(db_session, user.id, uuid4())
    assert out is None


@pytest.mark.asyncio
async def test_fetch_skips_deleted(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "fetch-deleted@example.com")
    rec = await _create_recording(db_session, user.id, title="X")
    rec.deleted_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    await db_session.commit()
    assert await fetch_recording_for_mcp(db_session, user.id, rec.id) is None


@pytest.mark.asyncio
async def test_fetch_respects_user_isolation(db_session: AsyncSession) -> None:
    user_a = await _create_user(db_session, "fetch-iso-a@example.com")
    user_b = await _create_user(db_session, "fetch-iso-b@example.com")
    rec = await _create_recording(db_session, user_b.id, title="B only")
    await db_session.commit()
    assert await fetch_recording_for_mcp(db_session, user_a.id, rec.id) is None


@pytest.mark.asyncio
async def test_fetch_returns_text_sections(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "fetch-full@example.com")
    rec = await _create_recording(db_session, user.id, title="Full Recording")
    db_session.add(Summary(
        recording_id=rec.id,
        summary="Top-line summary",
        key_points=["point one", "point two"],
        topics=["roadmap"],
        people_mentioned=["alice"],
        sentiment="positive",
    ))
    db_session.add(Segment(
        recording_id=rec.id, speaker="Alice", content="opener", start_ms=0,
    ))
    db_session.add(Segment(
        recording_id=rec.id, speaker="Bob", content="response", start_ms=1000,
    ))
    db_session.add(ActionItem(
        recording_id=rec.id, task="Ship docs",
        owner="Alice", due_date=date(2026, 6, 1),
    ))
    await db_session.commit()

    out = await fetch_recording_for_mcp(db_session, user.id, rec.id)
    assert out is not None
    assert out["title"] == "Full Recording"
    assert "Summary:\nTop-line summary" in out["text"]
    assert "Key points:\n- point one\n- point two" in out["text"]
    assert "Action items:\n- Ship docs (Alice) due 2026-06-01" in out["text"]
    assert "Alice: opener" in out["text"]
    assert "Bob: response" in out["text"]
    assert out["metadata"]["truncated"] is False
    assert out["metadata"]["topics"] == ["roadmap"]
    assert out["metadata"]["people_mentioned"] == ["alice"]


@pytest.mark.asyncio
async def test_fetch_minimal_recording_no_summary_no_segments(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "fetch-min@example.com")
    rec = await _create_recording(db_session, user.id, title=None)
    await db_session.commit()
    out = await fetch_recording_for_mcp(db_session, user.id, rec.id)
    assert out is not None
    assert out["title"] == "Untitled Recording"
    assert out["text"] == ""
    assert out["metadata"]["truncated"] is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_recording(
    db_session: AsyncSession,
    user_id: UUID,
    *,
    title: str | None = "Recording",
) -> Recording:
    rec = Recording(user_id=user_id, title=title, type="note", language="en")
    db_session.add(rec)
    await db_session.flush()
    return rec
