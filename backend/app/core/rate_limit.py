"""In-memory rate limiting for auth endpoints."""

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Simple in-memory sliding window rate limiter.

    Tracks request timestamps per key within a configurable window.
    Thread-safe via a lock on the shared state.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

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
            # Prune old entries
            timestamps = self._requests[key]
            self._requests[key] = [t for t in timestamps if t > cutoff]

            if len(self._requests[key]) >= max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                )

            self._requests[key].append(now)

    def reset(self) -> None:
        """Clear all tracked state. Primarily for testing."""
        with self._lock:
            self._requests.clear()


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
