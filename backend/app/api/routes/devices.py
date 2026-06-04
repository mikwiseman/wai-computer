"""Device presence + Mac-edge channel routes.

Heartbeat advertises reachability; later endpoints (drain approved desktop
actions, report results) ride the same registry so the cloud can deliver an
approved computer-use command to the right Mac and record what happened.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Database, SessionUser
from app.core.companion_actions import (
    ApprovalError,
    expire_due_actions,
    mark_failed,
    verify_committable,
)
from app.core.device_presence import device_online, get_owned_device, upsert_device
from app.models.agent import AgentRun
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
    user: SessionUser,
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
    chat_id: str | None = None
    agent_id: str | None = None
    agent_run_id: str | None = None
    tool: str
    args: dict[str, Any]
    preview: str


class DesktopActionQueue(BaseModel):
    actions: list[DesktopActionItem]


@router.get("/{device_id}/desktop-actions", response_model=DesktopActionQueue)
async def drain_desktop_actions(
    device_id: uuid.UUID,
    user: SessionUser,
    db: Database,
) -> DesktopActionQueue:
    """Approved desktop actions awaiting execution on this device. The Mac polls
    this, runs each via the native actuator, and reports back via
    /api/companion/chats/{chat_id}/actions/{action_id}/desktop_result. Returns
    only actions explicitly targeted at this device."""
    device = await get_owned_device(db, user_id=user.id, device_id=device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        )
    now = datetime.now(timezone.utc)
    expired_count = await expire_due_actions(db, now=now)
    rows = (
        await db.execute(
            select(CompanionPendingAction)
            .where(
                CompanionPendingAction.user_id == user.id,
                CompanionPendingAction.kind == "desktop_action",
                CompanionPendingAction.status == "approved",
                CompanionPendingAction.expires_at > now,
            )
            .order_by(CompanionPendingAction.created_at)
        )
    ).scalars().all()
    agent_run_ids = [row.agent_run_id for row in rows if row.agent_run_id is not None]
    run_by_id: dict[uuid.UUID, AgentRun] = {}
    if agent_run_ids:
        run_result = await db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user.id,
                AgentRun.id.in_(agent_run_ids),
            )
        )
        run_by_id = {run.id: run for run in run_result.scalars().all()}
    target = str(device_id)
    items: list[DesktopActionItem] = []
    failed_count = 0
    for row in rows:
        if row.device_target != target:
            continue
        try:
            verify_committable(row)
        except ApprovalError as exc:
            await mark_failed(db, row=row, detail=exc.message)
            failed_count += 1
            continue
        items.append(
            DesktopActionItem(
                action_id=str(row.id),
                chat_id=str(row.conversation_id) if row.conversation_id else None,
                agent_id=(
                    str(run_by_id[row.agent_run_id].agent_id)
                    if row.agent_run_id in run_by_id
                    else None
                ),
                agent_run_id=str(row.agent_run_id) if row.agent_run_id else None,
                tool=row.tool_name,
                args=(row.action_manifest or {}).get("args") or {},
                preview=(row.action_manifest or {}).get("preview", ""),
            )
        )
    if expired_count or failed_count:
        await db.commit()
    return DesktopActionQueue(actions=items)
