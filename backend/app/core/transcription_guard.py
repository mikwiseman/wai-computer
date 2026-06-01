"""Redis-backed cost + abuse guards for Deepgram transcription.

Centralises every fleet-wide control that bounds Deepgram spend and abuse:

- a master kill-switch (env + runtime Redis flag) to halt ALL Deepgram calls;
- realtime session-mint rate limiting (burst hard-cap + high daily backstop +
  sustained-rate alert), shared across gunicorn workers/replicas (the in-memory
  limiter under-counted by the worker count);
- global and per-user rolling daily audio-minute ceilings;
- a per-user / global concurrent realtime-stream lease (the /stream proxy bills
  per minute for the whole connection, not per mint);
- a circuit breaker that treats HTTP 402 (budget exceeded) as an immediate stop.

Design rules (see the 2026-05-31 cost-incident audit):
- FAIL OPEN. A Redis outage must never break transcription — every guard
  degrades to "allow" and emits a throttled anomaly so the degradation is
  visible. The provider-side Deepgram Budget API is the hard dollar floor.
- The kill-switch degrades to the env value (engaged only if env disables it),
  so a Redis blip cannot silently disable the operator's halt either.
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

# Key namespace (kept short; all under dg: so ops can SCAN/inspect easily).
_KILL_KEY = "dg:killswitch"
_BREAKER_FAILS = "dg:breaker:fails"
_BREAKER_OPEN = "dg:breaker:open"

_DAY_TTL_SECONDS = 172_800  # 2 days — keys are date-stamped; TTL is just cleanup.

_client: aioredis.Redis | None = None

# Throttle degradation anomalies so a Redis outage doesn't spam Sentry/Telegram.
_last_alert: dict[str, float] = {}
_ALERT_THROTTLE_SECONDS = 600.0


class TranscriptionGuardError(Exception):
    """A guard refused to authorise a Deepgram call.

    Carries a machine code + an optional Retry-After so HTTP call sites can map
    it to 429/503 and the Celery task can defer/fail without re-billing.
    """

    def __init__(self, code: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


def get_redis() -> aioredis.Redis:
    """Lazily build the shared async Redis client.

    Short socket timeouts so a Redis hang degrades fast instead of stalling a
    request; ``decode_responses`` so we work with str keys/values.
    """
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
        "transcription guard degraded alert_code=%s error_type=%s",
        alert_code,
        type(error).__name__,
    )
    try:
        from app.core.observability import capture_sentry_anomaly

        capture_sentry_anomaly(
            alert_code,
            "Transcription guard degraded (Redis unavailable) — failing open",
            category="transcription.guard",
            extras={"error_type": type(error).__name__},
            level="warning",
        )
    except Exception:  # pragma: no cover - alerting must never break the guard
        logger.exception("failed to emit guard-degraded anomaly")


# --------------------------------------------------------------------------- #
# Kill-switch
# --------------------------------------------------------------------------- #
async def transcription_halted() -> bool:
    """True if Deepgram calls must be refused.

    Engaged if the env disables transcription OR a runtime Redis flag is set
    (``SET dg:killswitch 1`` to halt, ``DEL dg:killswitch`` to resume). On a
    Redis error we fall back to the env value — a blip cannot silently disable
    the operator halt, nor halt a healthy system.
    """
    settings = get_settings()
    if not settings.transcription_enabled:
        return True
    try:
        return bool(await get_redis().exists(_KILL_KEY))
    except RedisError as exc:
        _degraded("transcription.guard.killswitch_degraded", exc)
        return False


# --------------------------------------------------------------------------- #
# Realtime session-mint rate guard (fleet-wide, replaces the in-memory limiter)
# --------------------------------------------------------------------------- #
async def register_mint(user_id: str, purpose: str) -> int:
    """Count a realtime session mint and enforce the rate guards.

    Raises ``TranscriptionGuardError`` on the burst hard-cap or the (high)
    daily backstop. Returns the approximate count of mints by this user in the
    trailing sustained window so the caller can emit an alert without blocking.
    Fails open on Redis error (returns 0).
    """
    settings = get_settings()
    now = time.time()
    burst_window = max(1, settings.realtime_mint_burst_window_seconds)
    sustained_window = max(1, settings.realtime_mint_sustained_window_seconds)
    daily_max = (
        settings.realtime_mint_daily_max_dictation
        if purpose == "dictation"
        else settings.realtime_mint_daily_max_recording
    )
    burst_key = f"dg:mint:burst:{user_id}:{int(now // burst_window)}"
    daily_key = f"dg:mint:daily:{purpose}:{user_id}:{_today()}"
    sustained_key = f"dg:mint:sustained:{user_id}:{int(now // sustained_window)}"
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(burst_key)
        pipe.expire(burst_key, burst_window * 2)
        pipe.incr(daily_key)
        pipe.expire(daily_key, _DAY_TTL_SECONDS)
        pipe.incr(sustained_key)
        pipe.expire(sustained_key, sustained_window * 2)
        results = await pipe.execute()
    except RedisError as exc:
        _degraded("transcription.guard.mint_degraded", exc)
        return 0
    burst_count = int(results[0])
    daily_count = int(results[2])
    sustained_count = int(results[4])
    if burst_count > settings.realtime_mint_burst_max:
        raise TranscriptionGuardError(
            "mint_burst",
            "Too many realtime sessions requested in a short window.",
            retry_after=burst_window,
        )
    if daily_max > 0 and daily_count > daily_max:
        raise TranscriptionGuardError(
            "mint_daily",
            "Daily realtime session limit reached.",
            retry_after=3600,
        )
    return sustained_count


# --------------------------------------------------------------------------- #
# Daily audio-minute ceilings (global + per-user)
# --------------------------------------------------------------------------- #
async def check_minutes_budget(user_id: str, estimated_minutes: float = 0.0) -> None:
    """Refuse if the global or per-user daily audio-minute ceiling is reached.

    No-op when ``transcription_abuse_caps_enabled`` is false or a cap is 0.
    Fails open on Redis error.
    """
    settings = get_settings()
    if not settings.transcription_abuse_caps_enabled:
        return
    global_cap = settings.deepgram_global_daily_minutes_cap
    user_cap = settings.deepgram_user_daily_minutes_cap
    if global_cap <= 0 and user_cap <= 0:
        return
    today = _today()
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.get(f"dg:min:global:{today}")
        pipe.get(f"dg:min:user:{user_id}:{today}")
        used_global_raw, used_user_raw = await pipe.execute()
    except RedisError as exc:
        _degraded("transcription.guard.minutes_degraded", exc)
        return
    used_global = float(used_global_raw or 0.0)
    used_user = float(used_user_raw or 0.0)
    if global_cap > 0 and used_global + estimated_minutes > global_cap:
        raise TranscriptionGuardError(
            "global_minutes",
            "Global daily transcription capacity reached. Please try again later.",
            retry_after=3600,
        )
    if user_cap > 0 and used_user + estimated_minutes > user_cap:
        raise TranscriptionGuardError(
            "user_minutes",
            "Daily transcription limit reached for your account.",
            retry_after=3600,
        )


async def record_minutes(user_id: str, minutes: float) -> None:
    """Add ``minutes`` of billed audio to the global + per-user daily counters."""
    if minutes <= 0:
        return
    today = _today()
    amount = round(float(minutes), 3)
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incrbyfloat(f"dg:min:global:{today}", amount)
        pipe.expire(f"dg:min:global:{today}", _DAY_TTL_SECONDS)
        pipe.incrbyfloat(f"dg:min:user:{user_id}:{today}", amount)
        pipe.expire(f"dg:min:user:{user_id}:{today}", _DAY_TTL_SECONDS)
        await pipe.execute()
    except RedisError as exc:
        _degraded("transcription.guard.record_minutes_degraded", exc)


# --------------------------------------------------------------------------- #
# Concurrent realtime-stream lease (the unit Deepgram actually bills)
# --------------------------------------------------------------------------- #
async def acquire_stream_slot(user_id: str, *, lease_ttl_seconds: int) -> str | None:
    """Try to claim a realtime-stream slot for ``user_id``.

    Uses a per-user and a global sorted-set keyed by lease token with score=now;
    stale leases (older than ``lease_ttl_seconds`` — a crashed socket that never
    released) are evicted before counting. Returns a lease token on success, or
    ``None`` if the per-user or global concurrency cap is reached. Fails open
    (returns a token) on Redis error.
    """
    settings = get_settings()
    user_max = settings.realtime_max_concurrent_streams_per_user
    global_max = settings.realtime_max_concurrent_streams_global
    token = uuid4().hex
    if user_max <= 0 and global_max <= 0:
        return token
    now = time.time()
    cutoff = now - max(1, lease_ttl_seconds)
    user_key = f"dg:stream:user:{user_id}"
    global_key = "dg:stream:global"
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
    except RedisError as exc:
        _degraded("transcription.guard.stream_slot_degraded", exc)
        return token


async def release_stream_slot(user_id: str, token: str | None) -> None:
    """Release a previously-acquired stream slot. Never raises."""
    if not token:
        return
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.zrem(f"dg:stream:user:{user_id}", token)
        pipe.zrem("dg:stream:global", f"{user_id}:{token}")
        await pipe.execute()
    except RedisError as exc:
        _degraded("transcription.guard.stream_release_degraded", exc)


# --------------------------------------------------------------------------- #
# Circuit breaker (treat HTTP 402 budget-exceeded as an immediate stop)
# --------------------------------------------------------------------------- #
async def provider_breaker_open() -> bool:
    """True if the Deepgram circuit breaker is open (fast-fail new work)."""
    if get_settings().deepgram_breaker_failure_threshold <= 0:
        return False
    try:
        return bool(await get_redis().exists(_BREAKER_OPEN))
    except RedisError as exc:
        _degraded("transcription.guard.breaker_read_degraded", exc)
        return False


async def record_provider_result(*, success: bool, status_code: int | None = None) -> None:
    """Feed a Deepgram call outcome to the circuit breaker.

    Success closes the breaker. HTTP 402 (budget exceeded) opens it immediately.
    A streak of other failures opens it once the threshold is reached.
    """
    settings = get_settings()
    threshold = settings.deepgram_breaker_failure_threshold
    if threshold <= 0:
        return
    cooldown = max(1, settings.deepgram_breaker_cooldown_seconds)
    try:
        r = get_redis()
        if success:
            await r.delete(_BREAKER_FAILS, _BREAKER_OPEN)
            return
        if status_code == 402:
            await r.set(_BREAKER_OPEN, "402", ex=cooldown)
            return
        pipe = r.pipeline()
        pipe.incr(_BREAKER_FAILS)
        pipe.expire(_BREAKER_FAILS, cooldown)
        results = await pipe.execute()
        if int(results[0]) >= threshold:
            await r.set(_BREAKER_OPEN, "streak", ex=cooldown)
    except RedisError as exc:
        _degraded("transcription.guard.breaker_write_degraded", exc)
