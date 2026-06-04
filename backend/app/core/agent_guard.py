"""Cost/abuse guard for autonomous working-agents (P6) — Redis-backed, FAIL OPEN.

A faithful clone of ``transcription_guard``: a kill-switch, a per-user + global
daily run ceiling, and a concurrency lease, all under the ``agents:`` key
namespace. **It fails OPEN** — a Redis outage must never wedge the agent fleet;
the *approval gate* (``companion_actions``) is the fail-CLOSED safety net, so a
permissive cost guard is the correct posture (plan invariant: "cost guard FAILS
OPEN, approval + trifecta gates FAIL CLOSED").

Call ``agents_halted`` + ``check_run_budget`` before dispatching a run, and lease
a slot with ``acquire_run_slot`` (release it when the run ends). On a guard
degradation we emit a throttled anomaly and allow the work through.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Key namespace — all under agents: so ops can SCAN/inspect easily.
_KILL_KEY = "agents:killswitch"
_DAY_TTL_SECONDS = 172_800  # 2 days — keys are date-stamped; TTL is just cleanup.

_client: aioredis.Redis | None = None

# Throttle degradation anomalies so a Redis outage doesn't spam Sentry/Telegram.
_last_alert: dict[str, float] = {}
_ALERT_THROTTLE_SECONDS = 600.0
_REDIS_DEGRADED_ERRORS = (RedisError, RuntimeError)


class AgentGuardError(Exception):
    """A guard refused to authorise an agent run.

    Carries a machine code + optional Retry-After so the caller can defer the
    run (re-schedule next tick) without losing it — never a silent drop.
    """

    def __init__(self, code: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


def get_redis() -> aioredis.Redis:
    """Lazily build the shared async Redis client (short timeouts so a hang
    degrades fast instead of stalling a worker)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
    return _client


def set_redis_for_tests(client: aioredis.Redis | None) -> None:
    """Inject a fake client (fakeredis) in tests; pass None to reset."""
    global _client
    _client = client
    _last_alert.clear()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _degraded(alert_code: str, error: Exception) -> None:
    """Record a guard degradation (Redis error) — throttled, never raises."""
    now = time.time()
    last = _last_alert.get(alert_code, 0.0)
    if now - last < _ALERT_THROTTLE_SECONDS:
        return
    _last_alert[alert_code] = now
    logger.warning(
        "agent guard degraded alert_code=%s error_type=%s",
        alert_code,
        type(error).__name__,
    )
    try:
        from app.core.observability import capture_sentry_anomaly

        capture_sentry_anomaly(
            alert_code,
            "Agent guard degraded (Redis unavailable) — failing open",
            category="agents.guard",
            extras={"error_type": type(error).__name__},
            level="warning",
        )
    except Exception:  # pragma: no cover - alerting must never break the guard
        logger.exception("failed to emit guard-degraded anomaly")


# --------------------------------------------------------------------------- #
# Kill-switch
# --------------------------------------------------------------------------- #
async def agents_halted() -> bool:
    """True if agent runs must be refused.

    Engaged if the env disables agents OR a runtime Redis flag is set
    (``SET agents:killswitch 1`` to halt, ``DEL agents:killswitch`` to resume).
    On a Redis error we fall back to the env value — a blip cannot silently halt
    a healthy fleet nor lift an operator halt.
    """
    settings = get_settings()
    if not settings.agents_enabled:
        return True
    try:
        return bool(await get_redis().exists(_KILL_KEY))
    except _REDIS_DEGRADED_ERRORS as exc:
        _degraded("agents.guard.killswitch_degraded", exc)
        return False


# --------------------------------------------------------------------------- #
# Daily run ceilings (global + per-user) — cost-runaway backstop
# --------------------------------------------------------------------------- #
async def check_run_budget(user_id: str) -> None:
    """Refuse if the global or per-user daily run ceiling is already reached.

    No-op when caps are disabled or 0. Fails open on Redis error.
    """
    settings = get_settings()
    if not settings.agent_abuse_caps_enabled:
        return
    global_cap = settings.agent_global_daily_runs_cap
    user_cap = settings.agent_user_daily_runs_cap
    if global_cap <= 0 and user_cap <= 0:
        return
    today = _today()
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.get(f"agents:runs:global:{today}")
        pipe.get(f"agents:runs:user:{user_id}:{today}")
        used_global_raw, used_user_raw = await pipe.execute()
    except _REDIS_DEGRADED_ERRORS as exc:
        _degraded("agents.guard.run_budget_degraded", exc)
        return
    used_global = int(used_global_raw or 0)
    used_user = int(used_user_raw or 0)
    if global_cap > 0 and used_global >= global_cap:
        raise AgentGuardError(
            "global_runs",
            "Global daily agent-run capacity reached. Try again later.",
            retry_after=3600,
        )
    if user_cap > 0 and used_user >= user_cap:
        raise AgentGuardError(
            "user_runs",
            "Daily agent-run limit reached for your account.",
            retry_after=3600,
        )


async def record_run(user_id: str) -> None:
    """Count a started run against the global + per-user daily counters."""
    today = _today()
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(f"agents:runs:global:{today}")
        pipe.expire(f"agents:runs:global:{today}", _DAY_TTL_SECONDS)
        pipe.incr(f"agents:runs:user:{user_id}:{today}")
        pipe.expire(f"agents:runs:user:{user_id}:{today}", _DAY_TTL_SECONDS)
        await pipe.execute()
    except _REDIS_DEGRADED_ERRORS as exc:
        _degraded("agents.guard.record_run_degraded", exc)


# --------------------------------------------------------------------------- #
# Concurrent-run lease (cap simultaneous runs per user + globally)
# --------------------------------------------------------------------------- #
async def acquire_run_slot(user_id: str, *, lease_ttl_seconds: int) -> str | None:
    """Try to claim a run slot for ``user_id``.

    Per-user + global sorted-sets keyed by lease token with score=now; stale
    leases (older than ``lease_ttl_seconds`` — a crashed worker that never
    released) are evicted before counting. Returns a token on success, or
    ``None`` if a concurrency cap is reached (the caller defers the run). Fails
    open (returns a token) on Redis error.
    """
    settings = get_settings()
    user_max = settings.agent_max_concurrent_runs_per_user
    global_max = settings.agent_max_concurrent_runs_global
    token = uuid4().hex
    if user_max <= 0 and global_max <= 0:
        return token
    now = time.time()
    cutoff = now - max(1, lease_ttl_seconds)
    user_key = f"agents:run:user:{user_id}"
    global_key = "agents:run:global"
    global_member = f"{user_id}:{token}"
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(user_key, 0, cutoff)
        pipe.zremrangebyscore(global_key, 0, cutoff)
        pipe.zcard(user_key)
        pipe.zcard(global_key)
        _, _, user_count, global_count = await pipe.execute()
        if user_max > 0 and int(user_count) >= user_max:
            return None
        if global_max > 0 and int(global_count) >= global_max:
            return None
        ttl = max(1, lease_ttl_seconds) * 2
        pipe = r.pipeline()
        pipe.zadd(user_key, {token: now})
        pipe.expire(user_key, ttl)
        pipe.zadd(global_key, {global_member: now})
        pipe.expire(global_key, ttl)
        await pipe.execute()
        return token
    except _REDIS_DEGRADED_ERRORS as exc:
        _degraded("agents.guard.run_slot_degraded", exc)
        return token


async def release_run_slot(user_id: str, token: str | None) -> None:
    """Release a previously-acquired run slot. Never raises."""
    if not token:
        return
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.zrem(f"agents:run:user:{user_id}", token)
        pipe.zrem("agents:run:global", f"{user_id}:{token}")
        await pipe.execute()
    except _REDIS_DEGRADED_ERRORS as exc:
        _degraded("agents.guard.run_release_degraded", exc)
