"""Mac-edge channel — device presence (heartbeat, online window, upsert)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest_asyncio

from app.core.device_presence import (
    DEVICE_ONLINE_WINDOW_SECONDS,
    device_online,
    get_owned_device,
    upsert_device,
)
from app.models.user import User


def test_device_online_window():
    now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert device_online(now - timedelta(seconds=10), now) is True
    assert (
        device_online(now - timedelta(seconds=DEVICE_ONLINE_WINDOW_SECONDS + 30), now)
        is False
    )
    assert device_online(None, now) is False


@pytest_asyncio.fixture
async def user_id(db_session):
    user = User(email=f"dev-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    return user.id


async def test_upsert_creates_then_refreshes_same_device(db_session, user_id):
    d1 = await upsert_device(db_session, user_id=user_id, platform="macos", name="MBP")
    assert d1.platform == "macos"
    assert d1.last_seen_at is not None
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    d2 = await upsert_device(
        db_session, user_id=user_id, platform="macos", name="MBP", now=later
    )
    assert d2.id == d1.id  # deduped by (user, platform, name)
    assert d2.last_seen_at == later


async def test_upsert_by_device_id_and_get_owned(db_session, user_id):
    d1 = await upsert_device(db_session, user_id=user_id, platform="macos", name="MBP")
    later = datetime.now(timezone.utc) + timedelta(seconds=60)
    d2 = await upsert_device(
        db_session,
        user_id=user_id,
        platform="macos",
        name="ignored",
        device_id=d1.id,
        now=later,
    )
    assert d2.id == d1.id  # matched by id, refreshed
    got = await get_owned_device(db_session, user_id=user_id, device_id=d1.id)
    assert got is not None and got.id == d1.id


async def test_heartbeat_route_registers_and_reuses(client, auth_headers):
    r = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "My Mac"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["online"] is True
    assert body["device_id"]

    r2 = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "My Mac", "device_id": body["device_id"]},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["device_id"] == body["device_id"]
