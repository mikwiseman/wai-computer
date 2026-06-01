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
