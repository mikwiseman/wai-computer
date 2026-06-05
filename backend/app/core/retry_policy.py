"""Retry classification for transient infrastructure/provider failures."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError

try:
    import openai
except Exception:  # pragma: no cover - import availability is dependency controlled.
    openai = None  # type: ignore[assignment]


def _status_is_retryable(status_code: int | None) -> bool:
    if status_code is None:
        return False
    return status_code in {408, 409, 425, 429} or 500 <= status_code < 600


def is_retryable_exception(exc: BaseException) -> bool:
    """Return true only for errors that can plausibly succeed on retry."""
    return any(_is_retryable_exception(item) for item in _exception_chain(exc))


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            current = None
        else:
            current = current.__context__


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return _status_is_retryable(exc.response.status_code)
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, (RedisConnectionError, RedisTimeoutError, OperationalError)):
        return True

    if openai is None:
        return False

    api_status_error = getattr(openai, "APIStatusError", None)
    if api_status_error is not None and isinstance(exc, api_status_error):
        return _status_is_retryable(getattr(exc, "status_code", None))

    retryable_names = (
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
    )
    retryable_classes = tuple(
        cls
        for name in retryable_names
        if (cls := getattr(openai, name, None)) is not None
    )
    return bool(retryable_classes) and isinstance(exc, retryable_classes)
