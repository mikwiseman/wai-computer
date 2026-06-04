"""Shared reminder API route tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import UserReminder
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _current_user_id(client: AsyncClient, headers: dict) -> str:
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_reminder_routes_create_list_and_cancel(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    due_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)

    created = await client.post(
        "/api/reminders",
        headers=auth_headers,
        json={"text": "Check launch metrics", "due_at": due_at.isoformat(), "source": "web"},
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    reminder_id = created_body["id"]
    assert created_body["text"] == "Check launch metrics"
    assert created_body["status"] == "pending"
    assert created_body["source"] == "web"
    assert created_body["due_at"] == due_at.isoformat().replace("+00:00", "Z")
    assert created_body["error"] is None

    listed = await client.get("/api/reminders", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["reminders"]] == [reminder_id]

    cancelled = await client.post(
        f"/api/reminders/{reminder_id}/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    pending = await client.get("/api/reminders", headers=auth_headers)
    assert pending.status_code == 200, pending.text
    assert pending.json()["reminders"] == []

    all_rows = await client.get("/api/reminders?status=all", headers=auth_headers)
    assert all_rows.status_code == 200, all_rows.text
    assert [row["status"] for row in all_rows.json()["reminders"]] == ["cancelled"]

    reminder = await db_session.get(UserReminder, UUID(reminder_id))
    assert reminder is not None
    assert reminder.status == "cancelled"
    assert reminder.text == "Check launch metrics"


async def test_reminder_routes_validate_time_and_user_ownership(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    other = User(email="other-reminders@example.com", password_hash="hash")
    db_session.add(other)
    await db_session.flush()
    other_reminder = UserReminder(
        user_id=other.id,
        source="api",
        text="Other user's reminder",
        due_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="pending",
    )
    db_session.add(other_reminder)
    await db_session.commit()

    naive = await client.post(
        "/api/reminders",
        headers=auth_headers,
        json={"text": "No timezone", "due_at": "2026-06-04T12:00:00"},
    )
    assert naive.status_code == 422, naive.text
    assert "timezone" in naive.json()["detail"]

    past = await client.post(
        "/api/reminders",
        headers=auth_headers,
        json={
            "text": "Past",
            "due_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert past.status_code == 422, past.text
    assert "future" in past.json()["detail"]

    empty_text = await client.post(
        "/api/reminders",
        headers=auth_headers,
        json={
            "text": "   ",
            "due_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    assert empty_text.status_code == 422, empty_text.text
    assert "empty" in empty_text.json()["detail"]

    listed = await client.get("/api/reminders?status=all", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["reminders"] == []

    cancel_other = await client.post(
        f"/api/reminders/{other_reminder.id}/cancel",
        headers=auth_headers,
    )
    assert cancel_other.status_code == 404, cancel_other.text

    rows = (
        await db_session.execute(select(UserReminder).where(UserReminder.user_id == UUID(user_id)))
    ).scalars().all()
    assert rows == []
