"""Cost/abuse kill-switch for MCP ingestion — the emergency stop.

A focused analogue of ``transcription_guard``: a fleet-wide + per-user
kill-switch so a runaway connect (or a misbehaving server) can be halted
instantly without a deploy. Reuses the shared async Redis client and FAILS OPEN
(a Redis blip must never wedge ingestion; the per-sync record cap + content-hash
dedup already bound a single sync's cost).

Engage:  ``redis-cli SET mi:killswitch 1``            (halt all MCP ingestion)
         ``redis-cli SET mi:killswitch:user:<id> 1``  (halt one user)
Resume:  ``redis-cli DEL mi:killswitch[...]``

(Per-user/global daily embed-token ceilings + a concurrency lease are a planned
extension; pre-v1.0 the kill-switch + per-sync cap + dedup are the controls.)
"""

from __future__ import annotations

import logging

from redis.exceptions import RedisError

from app.config import get_settings
from app.core.transcription_guard import get_redis

logger = logging.getLogger(__name__)

_KILL_KEY = "mi:killswitch"


async def mcp_ingestion_halted(user_id: str | object) -> bool:
    """True if MCP ingestion must be refused (global or per-user kill-switch).

    Falls back to the env setting on a Redis error so a blip cannot silently
    lift an operator halt nor halt a healthy system.
    """
    settings = get_settings()
    if not getattr(settings, "mcp_ingestion_enabled", True):
        return True
    try:
        redis = get_redis()
        if await redis.exists(_KILL_KEY):
            return True
        if await redis.exists(f"{_KILL_KEY}:user:{user_id}"):
            return True
        return False
    except RedisError:
        logger.warning("mcp ingest guard killswitch check degraded — failing open")
        return False
