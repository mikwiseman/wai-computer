"""Device presence for the Mac-edge channel.

A device is "online" if it heartbeated within ``DEVICE_ONLINE_WINDOW_SECONDS``.
The cloud checks this before dispatching an approved desktop action: online →
deliver now; offline → queue to the action's TTL + notify (time-insensitive) or
fail loudly (time-sensitive). No silent success.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device

# A heartbeat cadence well under this keeps a device "online"; a closed lid /
# crashed client falls out of the window so the cloud stops dispatching to it.
DEVICE_ONLINE_WINDOW_SECONDS = 90


def device_online(last_seen_at: datetime | None, now: datetime | None = None) -> bool:
    if last_seen_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - last_seen_at).total_seconds() <= DEVICE_ONLINE_WINDOW_SECONDS


async def upsert_device(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform: str,
    name: str | None,
    device_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Device:
    """Register/refresh a device and stamp last_seen_at. Matches an existing row
    by id (owner-scoped) or by (user, platform, name)."""
    now = now or datetime.now(timezone.utc)
    device: Device | None = None
    if device_id is not None:
        device = (
            await db.execute(
                select(Device).where(
                    Device.id == device_id, Device.user_id == user_id
                )
            )
        ).scalar_one_or_none()
    if device is None:
        device = (
            await db.execute(
                select(Device).where(
                    Device.user_id == user_id,
                    Device.platform == platform,
                    Device.name == name,
                )
            )
        ).scalar_one_or_none()
    if device is None:
        device = Device(
            user_id=user_id, platform=platform, name=name, last_seen_at=now
        )
        db.add(device)
        await db.flush()
        await db.refresh(device)
    else:
        device.last_seen_at = now
        await db.flush()
    return device


async def get_owned_device(
    db: AsyncSession, *, user_id: uuid.UUID, device_id: uuid.UUID
) -> Device | None:
    return (
        await db.execute(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )
    ).scalar_one_or_none()
