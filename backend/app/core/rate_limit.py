"""In-memory rate limiting for auth endpoints."""

import time
from threading import Lock

from fastapi import HTTPException, Request, status

# Run cleanup every 60 seconds at most
_CLEANUP_INTERVAL_SECONDS = 60


class RateLimiter:
    """Simple in-memory sliding window rate limiter.

    Tracks request timestamps per key within a configurable window.
    Thread-safe via a lock on the shared state.

    Periodically purges stale keys to prevent unbounded memory growth.
    """

    def __init__(self, cleanup_interval: int = _CLEANUP_INTERVAL_SECONDS) -> None:
        self._requests: dict[str, list[float]] = {}
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        # None means "not yet initialized" -- will be set on first check()
        self._last_cleanup: float | None = None
        # Track the max window any key has been checked with, so cleanup
        # can conservatively prune entries older than this.
        self._max_window: int = 0

    def _cleanup_stale_keys(self, now: float) -> None:
        """Remove keys with no timestamps within the max observed window.

        Must be called while holding self._lock.
        """
        if self._max_window == 0:
            return
        cutoff = now - self._max_window
        stale_keys = [
            k for k, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for k in stale_keys:
            del self._requests[k]
        self._last_cleanup = now

    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        """Check if the key has exceeded the rate limit.

        Args:
            key: Unique identifier (e.g., "login:192.168.1.1")
            max_requests: Maximum allowed requests in the window
            window_seconds: Time window in seconds

        Raises:
            HTTPException: 429 Too Many Requests if limit exceeded
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            if window_seconds > self._max_window:
                self._max_window = window_seconds

            # Periodic cleanup of stale keys to prevent memory leak
            if self._last_cleanup is None:
                self._last_cleanup = now
            elif now - self._last_cleanup >= self._cleanup_interval:
                self._cleanup_stale_keys(now)

            # Prune old entries for this key
            timestamps = self._requests.get(key)
            if timestamps:
                pruned = [t for t in timestamps if t > cutoff]
            else:
                pruned = []

            if len(pruned) >= max_requests:
                # Still store the pruned list (no new timestamp added)
                self._requests[key] = pruned
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                )

            pruned.append(now)
            self._requests[key] = pruned

    def count(self, key: str, window_seconds: int) -> int:
        """Return how many events for ``key`` fall within the trailing window.

        Read-only: does not record a new event and never raises. Used for
        early-warning signals (e.g. anomaly alerting) without affecting limits.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._requests.get(key)
            if not timestamps:
                return 0
            return sum(1 for t in timestamps if t > cutoff)

    def reset(self) -> None:
        """Clear all tracked state. Primarily for testing."""
        with self._lock:
            self._requests.clear()
            self._max_window = 0
            self._last_cleanup = None

    @property
    def key_count(self) -> int:
        """Return the number of tracked keys. Useful for testing memory behavior."""
        with self._lock:
            return len(self._requests)


# Module-level singleton
_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the global rate limiter instance."""
    return _limiter


def check_login_rate_limit(request: Request) -> None:
    """Dependency: 5 attempts per 60 seconds per IP for login."""
    limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(key=f"login:{client_ip}", max_requests=5, window_seconds=60)


def check_register_rate_limit(request: Request) -> None:
    """Dependency: 3 attempts per 60 seconds per IP for registration."""
    limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(key=f"register:{client_ip}", max_requests=3, window_seconds=60)


def check_magic_link_rate_limit(request: Request) -> None:
    """Dependency: 3 attempts per 60 seconds per IP for magic link requests."""
    limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(key=f"magic_link:{client_ip}", max_requests=3, window_seconds=60)


# --- Realtime transcription session-mint guardrails ------------------------
# Defense-in-depth against a client minting realtime tokens in a runaway loop
# (cause of the 2026-05-31 Deepgram cost incident). Tuned to NOT penalize power
# users: a long recording legitimately refreshes its token ~1/min for the whole
# meeting, and dictation is short bursts with gaps. The burst cap only blocks
# absurd pile-ups; daily caps are generous; a sustained-but-plausible rate only
# ALERTS (no block) so ops can distinguish heavy use from error/abuse.
REALTIME_MINT_BURST_MAX = 20
REALTIME_MINT_BURST_WINDOW_SECONDS = 60
REALTIME_MINT_DAILY_MAX = {
    "dictation": 360,  # ~6h-equivalent of dictation tokens per day
    "recording": 900,  # ~15h-equivalent per day (long meetings are legitimate)
}
REALTIME_MINT_DAILY_WINDOW_SECONDS = 86_400
REALTIME_MINT_SUSTAINED_WINDOW_SECONDS = 900  # 15 minutes
REALTIME_MINT_SUSTAINED_ALERT = 45  # >45 mints / 15 min -> anomaly alert (no block)


def check_realtime_session_mint_rate_limit(user_id: str, purpose: str) -> int:
    """Guard POST /transcription/session against runaway/abusive token minting.

    Raises HTTPException(429) on an absurd burst or a generous per-purpose daily
    cap. Returns the number of mints by this (user, purpose) within the trailing
    sustained window so the caller can emit an early-warning anomaly without
    blocking legitimate power users.
    """
    limiter = get_rate_limiter()
    limiter.check(
        key=f"rt_mint_burst:{user_id}",
        max_requests=REALTIME_MINT_BURST_MAX,
        window_seconds=REALTIME_MINT_BURST_WINDOW_SECONDS,
    )
    daily_key = f"rt_mint_daily:{purpose}:{user_id}"
    limiter.check(
        key=daily_key,
        max_requests=REALTIME_MINT_DAILY_MAX.get(purpose, REALTIME_MINT_DAILY_MAX["recording"]),
        window_seconds=REALTIME_MINT_DAILY_WINDOW_SECONDS,
    )
    return limiter.count(daily_key, REALTIME_MINT_SUSTAINED_WINDOW_SECONDS)
