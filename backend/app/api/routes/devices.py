"""Device presence + Mac-edge channel routes.

Heartbeat advertises reachability; later endpoints (drain approved desktop
actions, report results) ride the same registry so the cloud can deliver an
approved computer-use command to the right Mac and record what happened.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.device_presence import device_online, get_owned_device, upsert_device
from app.models.companion_pending_action import CompanionPendingAction

router = APIRouter(prefix="/devices", tags=["devices"])


class HeartbeatRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=200)
    device_id: uuid.UUID | None = None


class HeartbeatResponse(BaseModel):
    device_id: str
    online: bool


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    request: HeartbeatRequest,
    user: CurrentUser,
    db: Database,
) -> HeartbeatResponse:
    """Register/refresh this device and stamp its presence."""
    device = await upsert_device(
        db,
        user_id=user.id,
        platform=request.platform,
        name=request.name,
        device_id=request.device_id,
    )
    await db.commit()
    return HeartbeatResponse(
        device_id=str(device.id),
        online=device_online(device.last_seen_at),
    )


class DesktopActionItem(BaseModel):
    action_id: str
    tool: str
    args: dict[str, Any]
    preview: str


class DesktopActionQueue(BaseModel):
    actions: list[DesktopActionItem]


@router.get("/{device_id}/desktop-actions", response_model=DesktopActionQueue)
async def drain_desktop_actions(
    device_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> DesktopActionQueue:
    """Approved desktop actions awaiting execution on this device. The Mac polls
    this, runs each via the native actuator, and reports back via
    /api/companion/chats/{chat_id}/actions/{action_id}/desktop_result. Returns
    actions targeted at this device or to any device (device_target null)."""
    device = await get_owned_device(db, user_id=user.id, device_id=device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        )
    rows = (
        await db.execute(
            select(CompanionPendingAction)
            .where(
                CompanionPendingAction.user_id == user.id,
                CompanionPendingAction.kind == "desktop_action",
                CompanionPendingAction.status == "approved",
            )
            .order_by(CompanionPendingAction.created_at)
        )
    ).scalars().all()
    target = str(device_id)
    items = [
        DesktopActionItem(
            action_id=str(row.id),
            tool=row.tool_name,
            args=(row.action_manifest or {}).get("args") or {},
            preview=(row.action_manifest or {}).get("preview", ""),
        )
        for row in rows
        if row.device_target in (None, target)
    ]
    return DesktopActionQueue(actions=items)
