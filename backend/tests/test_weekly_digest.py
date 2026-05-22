"""Tests for the weekly digest endpoint."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.highlight import Highlight
from app.models.recording import ActionItem, Recording, Segment, Summary
from tests.conftest import LEGAL_ACCEPTANCE


async def _create_user(client: AsyncClient) -> tuple[dict, str]:
    """Create a user and return (auth_headers, user_email)."""
    email = f"digest-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpass123", **LEGAL_ACCEPTANCE},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def _seed_recording(
    db: AsyncSession,
    user_id,
    *,
    title: str = "Test Recording",
    rec_type: str = "meeting",
    duration: int = 300,
    created_days_ago: int = 0,
    add_summary: bool = False,
    topics: list[str] | None = None,
    people: list[str] | None = None,
    sentiment: str = "neutral",
    add_action_items: int = 0,
    add_highlights: int = 0,
    status: str = "ready",
):
    """Insert a recording (and optional related rows) directly into the DB."""
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(days=created_days_ago)

    rec = Recording(
        user_id=user_id,
        title=title,
        type=rec_type,
        status=status,
        duration_seconds=duration,
        created_at=created_at,
    )
    db.add(rec)
    await db.flush()

    # Add a single segment so the recording has content
    db.add(
        Segment(
            recording_id=rec.id,
            speaker="Speaker 1",
            content="Hello world",
            start_ms=0,
            end_ms=duration * 1000,
        )
    )

    if add_summary:
        db.add(
            Summary(
                recording_id=rec.id,
                summary="A test summary.",
                key_points=["Point 1"],
                decisions=[],
                topics=topics or [],
                people_mentioned=people or [],
                sentiment=sentiment,
            )
        )

    for i in range(add_action_items):
        db.add(
            ActionItem(
                recording_id=rec.id,
                task=f"Action item {i + 1}",
                owner="Alice",
                priority="medium",
                status="pending",
                source="generated",
            )
        )

    for i in range(add_highlights):
        db.add(
            Highlight(
                recording_id=rec.id,
                category="insight",
                title=f"Highlight {i + 1}",
                description="An important moment",
                importance="high",
            )
        )

    await db.commit()
    return rec


async def _get_user_id(client: AsyncClient, headers: dict):
    """Get the user ID from the auth headers."""
    resp = await client.get("/api/auth/me", headers=headers)
    return resp.json()["id"]


# ---- Tests ----


@pytest.mark.asyncio
async def test_weekly_digest_empty(client: AsyncClient, db_session: AsyncSession):
    """Digest with no recordings returns zeroed-out structure."""
    headers, _ = await _create_user(client)

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["total_recordings"] == 0
    assert data["total_duration_seconds"] == 0
    assert data["recordings_by_type"] == {}
    assert data["top_topics"] == []
    assert data["top_people"] == []
    assert data["pending_action_items"] == []
    assert data["highlights"] == []
    assert isinstance(data["daily_breakdown"], list)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)


@pytest.mark.asyncio
async def test_weekly_digest_counts_recent_recordings(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest counts only recordings from the last 7 days."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    # 2 recordings within the week
    await _seed_recording(db_session, user_id, title="Today", created_days_ago=0, duration=600)
    await _seed_recording(db_session, user_id, title="3 days ago", created_days_ago=3, duration=300)
    # 1 recording outside the week (should be excluded)
    await _seed_recording(db_session, user_id, title="Old", created_days_ago=10, duration=100)

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["total_recordings"] == 2
    assert data["total_duration_seconds"] == 900  # 600 + 300


@pytest.mark.asyncio
async def test_weekly_digest_type_breakdown(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest returns correct recordings_by_type counts."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(db_session, user_id, rec_type="meeting", created_days_ago=1)
    await _seed_recording(db_session, user_id, rec_type="meeting", created_days_ago=2)
    await _seed_recording(db_session, user_id, rec_type="note", created_days_ago=1)

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert data["recordings_by_type"]["meeting"] == 2
    assert data["recordings_by_type"]["note"] == 1


@pytest.mark.asyncio
async def test_weekly_digest_aggregates_topics(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest aggregates and ranks topics from summaries."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(
        db_session, user_id, created_days_ago=1,
        add_summary=True, topics=["AI", "Product"],
    )
    await _seed_recording(
        db_session, user_id, created_days_ago=2,
        add_summary=True, topics=["AI", "Design"],
    )

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    # "AI" appears twice, should be first
    assert len(data["top_topics"]) >= 2
    assert data["top_topics"][0]["topic"] == "AI"
    assert data["top_topics"][0]["count"] == 2


@pytest.mark.asyncio
async def test_weekly_digest_aggregates_people(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest aggregates and ranks people mentioned across recordings."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(
        db_session, user_id, created_days_ago=0,
        add_summary=True, people=["Alice", "Bob"],
    )
    await _seed_recording(
        db_session, user_id, created_days_ago=1,
        add_summary=True, people=["Alice", "Charlie"],
    )

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert len(data["top_people"]) >= 2
    assert data["top_people"][0]["name"] == "Alice"
    assert data["top_people"][0]["count"] == 2


@pytest.mark.asyncio
async def test_weekly_digest_pending_action_items(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest returns pending action items from the week."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(
        db_session, user_id, created_days_ago=1, add_action_items=3,
    )

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert len(data["pending_action_items"]) == 3
    assert data["pending_action_items"][0]["task"] == "Action item 1"


@pytest.mark.asyncio
async def test_weekly_digest_includes_highlights(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest returns highlights from the week's recordings."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(
        db_session, user_id, created_days_ago=0, add_highlights=2,
    )

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert len(data["highlights"]) == 2
    assert data["highlights"][0]["title"] == "Highlight 1"


@pytest.mark.asyncio
async def test_weekly_digest_daily_breakdown(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest daily_breakdown has 7 entries with correct counts."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(db_session, user_id, created_days_ago=0, duration=100)
    await _seed_recording(db_session, user_id, created_days_ago=0, duration=200)
    await _seed_recording(db_session, user_id, created_days_ago=3, duration=500)

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert len(data["daily_breakdown"]) == 7

    # The most recent day should have 2 recordings
    today_entry = data["daily_breakdown"][-1]
    assert today_entry["count"] == 2
    assert today_entry["duration_seconds"] == 300


@pytest.mark.asyncio
async def test_weekly_digest_excludes_deleted(
    client: AsyncClient, db_session: AsyncSession
):
    """Deleted recordings are excluded from the digest."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    # Create a normal recording
    await _seed_recording(db_session, user_id, title="Active", created_days_ago=1)
    # Create and soft-delete a recording
    deleted_rec = await _seed_recording(
        db_session, user_id, title="Deleted", created_days_ago=1,
    )
    deleted_rec.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert data["total_recordings"] == 1


@pytest.mark.asyncio
async def test_weekly_digest_excludes_other_users(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest only includes the authenticated user's recordings."""
    headers1, _ = await _create_user(client)
    headers2, _ = await _create_user(client)
    user1_id = await _get_user_id(client, headers1)
    user2_id = await _get_user_id(client, headers2)

    await _seed_recording(db_session, user1_id, title="User1 rec", created_days_ago=0)
    await _seed_recording(db_session, user2_id, title="User2 rec", created_days_ago=0)

    resp = await client.get("/api/recordings/digest/weekly", headers=headers1)
    data = resp.json()

    assert data["total_recordings"] == 1


@pytest.mark.asyncio
async def test_weekly_digest_sentiment_breakdown(
    client: AsyncClient, db_session: AsyncSession
):
    """Digest includes sentiment distribution across recordings."""
    headers, _ = await _create_user(client)
    user_id = await _get_user_id(client, headers)

    await _seed_recording(
        db_session, user_id, created_days_ago=0,
        add_summary=True, sentiment="positive",
    )
    await _seed_recording(
        db_session, user_id, created_days_ago=1,
        add_summary=True, sentiment="positive",
    )
    await _seed_recording(
        db_session, user_id, created_days_ago=2,
        add_summary=True, sentiment="negative",
    )

    resp = await client.get("/api/recordings/digest/weekly", headers=headers)
    data = resp.json()

    assert data["sentiment_breakdown"]["positive"] == 2
    assert data["sentiment_breakdown"]["negative"] == 1


@pytest.mark.asyncio
async def test_weekly_digest_unauthenticated(client: AsyncClient):
    """Unauthenticated requests return 401."""
    resp = await client.get("/api/recordings/digest/weekly")
    assert resp.status_code == 401
