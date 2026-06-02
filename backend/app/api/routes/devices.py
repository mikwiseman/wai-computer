"""Device presence + Mac-edge channel routes.

Heartbeat advertises reachability; later endpoints (drain approved desktop
actions, report results) ride the same registry so the cloud can deliver an
approved computer-use command to the right Mac and record what happened.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database
from app.core.device_presence import device_online, upsert_device

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
