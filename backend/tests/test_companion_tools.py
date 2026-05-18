"""Direct tests for app.core.companion._tool_* implementations.

The existing test_companion_loop.py exercises the full turn loop with a mocked
OpenAI client; that gives incidental coverage of the tool happy-paths but
skips most of the input-validation branches. This file targets those branches
directly so app/core/companion.py reaches 95% on the lower half of the file
(tool implementations)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import companion as comp
from app.core.companion import (
    CompanionError,
    _tool_get_action_items,
    _tool_get_highlights,
    _tool_get_recording_summary,
    _tool_list_recordings,
    _tool_search_people,
    _tool_search_transcripts,
)
from app.models.entity import Entity, EntityRelation
from app.models.highlight import Highlight
from app.models.recording import ActionItem, Folder, Recording, Segment, Summary
from app.models.user import User


# ---------------------------------------------------------------------------
# _tool_search_transcripts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_transcripts_rejects_empty_query(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "search-trans-empty@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_search_transcripts(db_session, user.id, {"query": ""}, None)
    assert exc.value.code == "invalid_tool_args"


@pytest.mark.asyncio
async def test_search_transcripts_rejects_whitespace_query(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "search-trans-ws@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_search_transcripts(db_session, user.id, {"query": "   "}, None)
    assert exc.value.code == "invalid_tool_args"


@pytest.mark.asyncio
async def test_search_transcripts_rejects_non_string_query(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "search-trans-int@example.com")
    with pytest.raises(CompanionError):
        await _tool_search_transcripts(db_session, user.id, {"query": 123}, None)


@pytest.mark.asyncio
async def test_search_transcripts_rejects_malformed_recording_ids(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "search-trans-bad-rid@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_search_transcripts(
            db_session, user.id,
            {"query": "x", "recording_ids": ["not-a-uuid"]}, None,
        )
    assert exc.value.code == "invalid_tool_args"
    assert "malformed id" in exc.value.message


@pytest.mark.asyncio
async def test_search_transcripts_returns_empty_when_no_data(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "search-trans-empty-db@example.com")
    out = await _tool_search_transcripts(
        db_session, user.id, {"query": "anything"}, None,
    )
    assert out.payload_for_model == {"segments": []}
    assert out.citable_segments == {}
    assert "segments" in out.summary_for_event


# ---------------------------------------------------------------------------
# _tool_get_recording_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recording_summary_rejects_missing_id(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "summary-no-id@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_get_recording_summary(db_session, user.id, {}, None)
    assert exc.value.code == "invalid_tool_args"


@pytest.mark.asyncio
async def test_get_recording_summary_rejects_malformed_id(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "summary-bad-id@example.com")
    with pytest.raises(CompanionError):
        await _tool_get_recording_summary(
            db_session, user.id, {"recording_id": "not-a-uuid"}, None,
        )


@pytest.mark.asyncio
async def test_get_recording_summary_returns_not_found_payload(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "summary-not-found@example.com")
    out = await _tool_get_recording_summary(
        db_session, user.id, {"recording_id": str(uuid.uuid4())}, None,
    )
    assert out.payload_for_model["ok"] is False
    assert out.payload_for_model["reason"] == "summary_not_found"


@pytest.mark.asyncio
async def test_get_recording_summary_returns_out_of_scope_payload(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "summary-oos@example.com")
    rec = await _create_recording(db_session, user.id)
    db_session.add(Summary(recording_id=rec.id, summary="..."))
    await db_session.commit()

    other_id = uuid.uuid4()
    scope = {"recording_ids": [str(other_id)]}
    out = await _tool_get_recording_summary(
        db_session, user.id, {"recording_id": str(rec.id)}, scope,
    )
    assert out.payload_for_model["ok"] is False
    assert out.payload_for_model["reason"] == "out_of_scope"


@pytest.mark.asyncio
async def test_get_recording_summary_returns_full_summary_payload(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "summary-ok@example.com")
    rec = await _create_recording(db_session, user.id, title="Roadmap")
    db_session.add(Summary(
        recording_id=rec.id,
        summary="The team discussed Q3.",
        key_points=["Ship in July"],
        topics=["roadmap"],
        people_mentioned=["alice"],
        decisions=["Approve Plan A"],
        sentiment="positive",
    ))
    await db_session.commit()

    out = await _tool_get_recording_summary(
        db_session, user.id, {"recording_id": str(rec.id)}, None,
    )
    assert out.payload_for_model["ok"] is True
    assert out.payload_for_model["recording_title"] == "Roadmap"
    assert out.payload_for_model["summary"] == "The team discussed Q3."
    assert out.payload_for_model["sentiment"] == "positive"
    assert out.summary_for_event.startswith("summary for")


# ---------------------------------------------------------------------------
# _tool_list_recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recordings_rejects_invalid_date_from(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "list-bad-from@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_list_recordings(
            db_session, user.id, {"date_from": "not-iso"}, None,
        )
    assert "date_from" in exc.value.message


@pytest.mark.asyncio
async def test_list_recordings_rejects_invalid_date_to(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "list-bad-to@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_list_recordings(
            db_session, user.id, {"date_to": "not-iso"}, None,
        )
    assert "date_to" in exc.value.message


@pytest.mark.asyncio
async def test_list_recordings_includes_folder_and_summary_one_line(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "list-with-folder@example.com")
    folder = Folder(user_id=user.id, name="Q3 Planning")
    db_session.add(folder)
    await db_session.flush()

    rec = Recording(
        user_id=user.id, title="Sprint review", type="meeting",
        language="en", folder_id=folder.id,
    )
    db_session.add(rec)
    await db_session.flush()
    db_session.add(Summary(
        recording_id=rec.id,
        summary="First sentence. Second sentence.",
        key_points=["a"], topics=["sprint"],
    ))
    await db_session.commit()

    out = await _tool_list_recordings(db_session, user.id, {}, None)
    entries = out.payload_for_model["recordings"]
    assert len(entries) == 1
    assert entries[0]["folder"] == "Q3 Planning"
    assert entries[0]["summary_one_line"] == "First sentence."
    assert entries[0]["topics"] == ["sprint"]


@pytest.mark.asyncio
async def test_list_recordings_filters_by_date_range(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "list-date-filter@example.com")
    rec = await _create_recording(db_session, user.id, title="Recent")
    await db_session.commit()

    # date_from in the future excludes everything
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    out = await _tool_list_recordings(
        db_session, user.id, {"date_from": future}, None,
    )
    assert out.payload_for_model["recordings"] == []


@pytest.mark.asyncio
async def test_list_recordings_with_scope(db_session: AsyncSession) -> None:
    user = await _create_user(db_session, "list-scoped@example.com")
    rec1 = await _create_recording(db_session, user.id, title="In scope")
    rec2 = await _create_recording(db_session, user.id, title="Out of scope")
    await db_session.commit()

    scope = {"recording_ids": [str(rec1.id)]}
    out = await _tool_list_recordings(db_session, user.id, {}, scope)
    titles = [r["title"] for r in out.payload_for_model["recordings"]]
    assert "In scope" in titles
    assert "Out of scope" not in titles


# ---------------------------------------------------------------------------
# _tool_get_action_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_items_rejects_invalid_due_before(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "ai-bad-due@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_get_action_items(
            db_session, user.id, {"due_before": "not-iso"}, None,
        )
    assert "due_before" in exc.value.message


@pytest.mark.asyncio
async def test_get_action_items_default_status_is_pending(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "ai-pending@example.com")
    rec = await _create_recording(db_session, user.id)
    db_session.add(ActionItem(
        recording_id=rec.id, task="Done thing", status="completed",
        priority="medium",
    ))
    db_session.add(ActionItem(
        recording_id=rec.id, task="Pending thing", status="pending",
        priority="high",
    ))
    await db_session.commit()

    out = await _tool_get_action_items(db_session, user.id, {}, None)
    items = out.payload_for_model["action_items"]
    tasks = [i["task"] for i in items]
    assert "Pending thing" in tasks
    assert "Done thing" not in tasks


@pytest.mark.asyncio
async def test_get_action_items_filter_by_status(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "ai-status@example.com")
    rec = await _create_recording(db_session, user.id)
    db_session.add(ActionItem(
        recording_id=rec.id, task="Done thing", status="completed",
        priority="medium",
    ))
    await db_session.commit()

    out = await _tool_get_action_items(
        db_session, user.id, {"status": "completed"}, None,
    )
    tasks = [i["task"] for i in out.payload_for_model["action_items"]]
    assert "Done thing" in tasks


@pytest.mark.asyncio
async def test_get_action_items_filter_by_priority_owner_due(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "ai-filters@example.com")
    rec = await _create_recording(db_session, user.id)
    db_session.add(ActionItem(
        recording_id=rec.id, task="High prio Alice", status="pending",
        priority="high", owner="alice", due_date=date(2026, 6, 1),
    ))
    db_session.add(ActionItem(
        recording_id=rec.id, task="Low prio Bob", status="pending",
        priority="low", owner="bob", due_date=date(2027, 1, 1),
    ))
    await db_session.commit()

    out = await _tool_get_action_items(
        db_session, user.id,
        {"priority": "high", "owner": "alice", "due_before": "2026-12-31"},
        None,
    )
    tasks = [i["task"] for i in out.payload_for_model["action_items"]]
    assert tasks == ["High prio Alice"]


# ---------------------------------------------------------------------------
# _tool_get_highlights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_highlights_rejects_invalid_min_importance(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "hl-bad-imp@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_get_highlights(
            db_session, user.id, {"min_importance": "extreme"}, None,
        )
    assert "min_importance" in exc.value.message


@pytest.mark.asyncio
async def test_get_highlights_rejects_invalid_date_from(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "hl-bad-from@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_get_highlights(
            db_session, user.id, {"date_from": "not-iso"}, None,
        )
    assert "date_from" in exc.value.message


@pytest.mark.asyncio
async def test_get_highlights_rejects_invalid_date_to(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "hl-bad-to@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_get_highlights(
            db_session, user.id, {"date_to": "not-iso"}, None,
        )
    assert "date_to" in exc.value.message


@pytest.mark.asyncio
async def test_get_highlights_filter_by_category_and_importance(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "hl-filter@example.com")
    rec = await _create_recording(db_session, user.id)
    db_session.add(Highlight(
        recording_id=rec.id, category="decision",
        title="Key decision", description="d",
        importance="high", start_ms=0, end_ms=1000,
    ))
    db_session.add(Highlight(
        recording_id=rec.id, category="insight",
        title="Low importance", description="d",
        importance="low", start_ms=0, end_ms=1000,
    ))
    await db_session.commit()

    out = await _tool_get_highlights(
        db_session, user.id,
        {"category": "decision", "min_importance": "high"}, None,
    )
    titles = [h["title"] for h in out.payload_for_model["highlights"]]
    assert "Key decision" in titles
    assert "Low importance" not in titles


# ---------------------------------------------------------------------------
# _tool_search_people
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_people_rejects_empty_name(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "people-empty@example.com")
    with pytest.raises(CompanionError) as exc:
        await _tool_search_people(db_session, user.id, {"name": ""}, None)
    assert exc.value.code == "invalid_tool_args"


@pytest.mark.asyncio
async def test_search_people_rejects_whitespace_name(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "people-ws@example.com")
    with pytest.raises(CompanionError):
        await _tool_search_people(db_session, user.id, {"name": "  "}, None)


@pytest.mark.asyncio
async def test_search_people_rejects_non_string_name(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "people-int@example.com")
    with pytest.raises(CompanionError):
        await _tool_search_people(db_session, user.id, {"name": 42}, None)


@pytest.mark.asyncio
async def test_search_people_no_match_returns_empty(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "people-nomatch@example.com")
    out = await _tool_search_people(
        db_session, user.id, {"name": "NoSuchPerson"}, None,
    )
    assert out.payload_for_model == {"recordings": [], "matched_entities": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="hash")
    db.add(user)
    await db.flush()
    return user


async def _create_recording(
    db: AsyncSession, user_id: uuid.UUID, *, title: str | None = "Recording",
) -> Recording:
    rec = Recording(user_id=user_id, title=title, type="note", language="en")
    db.add(rec)
    await db.flush()
    return rec
