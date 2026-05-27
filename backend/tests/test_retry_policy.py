"""Retry classification tests for background processing."""

from __future__ import annotations

import httpx
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError

from app.core.retry_policy import _status_is_retryable, is_retryable_exception


def test_retry_policy_retries_transient_http_statuses() -> None:
    request = httpx.Request("POST", "https://provider.example/stt")
    retryable = httpx.Response(503, request=request)
    deterministic = httpx.Response(400, request=request)

    assert is_retryable_exception(
        httpx.HTTPStatusError("server error", request=request, response=retryable)
    )
    assert not is_retryable_exception(
        httpx.HTTPStatusError("bad request", request=request, response=deterministic)
    )


def test_retry_policy_retries_network_timeouts_only() -> None:
    assert is_retryable_exception(httpx.TimeoutException("timeout"))
    assert not is_retryable_exception(ValueError("unsupported provider"))


def test_status_without_http_code_is_not_retryable() -> None:
    assert not _status_is_retryable(None)


def test_retry_policy_retries_infrastructure_errors() -> None:
    assert is_retryable_exception(RedisConnectionError("redis down"))
    assert is_retryable_exception(RedisTimeoutError("redis timeout"))
    assert is_retryable_exception(OperationalError("select 1", {}, RuntimeError("db down")))
