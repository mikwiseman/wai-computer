"""Retry classification tests for background processing."""

from __future__ import annotations

import httpx
import openai
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError

from app.core.retry_policy import (
    _status_is_retryable,
    is_openai_insufficient_quota,
    is_retryable_exception,
)


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


def test_retry_policy_retries_wrapped_transient_errors() -> None:
    request = httpx.Request("POST", "https://provider.example/chat")
    cause = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=httpx.Response(429, request=request),
    )

    try:
        raise RuntimeError("summarizer wrapped provider error") from cause
    except RuntimeError as exc:
        assert is_retryable_exception(exc)


def test_retry_policy_stops_at_suppressed_exception_context() -> None:
    try:
        try:
            raise httpx.TimeoutException("hidden context")
        except httpx.TimeoutException:
            raise RuntimeError("suppressed") from None
    except RuntimeError as exc:
        assert not is_retryable_exception(exc)


def test_retry_policy_does_not_retry_openai_insufficient_quota() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(429, request=request)
    exc = openai.RateLimitError(
        "quota exhausted",
        response=response,
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )

    assert not is_retryable_exception(exc)


def test_openai_insufficient_quota_detects_direct_error_attributes() -> None:
    class DirectQuotaError(Exception):
        code = "insufficient_quota"

    assert is_openai_insufficient_quota(DirectQuotaError("quota exhausted"))
