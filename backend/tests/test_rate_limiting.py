"""Tests for auth endpoint rate limiting."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.rate_limit import RateLimiter, get_rate_limiter

# --- Unit tests for RateLimiter class ---


class TestRateLimiterUnit:
    """Unit tests for the RateLimiter class (no HTTP, no DB)."""

    def test_allows_requests_within_limit(self):
        limiter = RateLimiter()
        # Should not raise for requests within limit
        for _ in range(5):
            limiter.check("test_key", max_requests=5, window_seconds=60)

    def test_blocks_requests_exceeding_limit(self):
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("test_key", max_requests=3, window_seconds=60)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            limiter.check("test_key", max_requests=3, window_seconds=60)
        assert exc_info.value.status_code == 429
        assert "Too many requests" in exc_info.value.detail

    def test_different_keys_are_independent(self):
        limiter = RateLimiter()
        # Fill up key_a
        for _ in range(3):
            limiter.check("key_a", max_requests=3, window_seconds=60)

        # key_b should still work
        limiter.check("key_b", max_requests=3, window_seconds=60)

    def test_reset_clears_all_state(self):
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("test_key", max_requests=3, window_seconds=60)

        limiter.reset()

        # Should work again after reset
        limiter.check("test_key", max_requests=3, window_seconds=60)

    def test_expired_entries_are_pruned(self):
        from unittest.mock import patch

        limiter = RateLimiter()

        # Add requests at a fake early time
        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(3):
                limiter.check("test_key", max_requests=3, window_seconds=60)

        # Now advance time past the window
        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1061.0  # 61 seconds later
            # Old entries should be pruned, so this should succeed
            limiter.check("test_key", max_requests=3, window_seconds=60)

    def test_get_rate_limiter_returns_singleton(self):
        a = get_rate_limiter()
        b = get_rate_limiter()
        assert a is b


# --- Integration tests for rate-limited endpoints ---


@pytest.mark.asyncio
async def test_login_rate_limit_allows_normal_usage(client: AsyncClient):
    """Login should work normally within the rate limit."""
    # Register a user
    email = f"ratelimit-login-{uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )

    # 5 login attempts should all be allowed (even if credentials are wrong)
    for i in range(5):
        response = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "password123"},
        )
        assert response.status_code == 200, f"Request {i+1} was blocked unexpectedly"


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_after_exceeded(client: AsyncClient):
    """Login should return 429 after 5 attempts per minute."""
    email = f"ratelimit-block-{uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )

    # Use up the 5 allowed attempts
    for _ in range(5):
        await client.post(
            "/api/auth/login",
            json={"email": email, "password": "password123"},
        )

    # 6th attempt should be blocked
    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_rate_limit_allows_normal_usage(client: AsyncClient):
    """Registration should work within the rate limit."""
    for i in range(3):
        email = f"ratelimit-reg-{uuid4().hex[:8]}@example.com"
        response = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        assert response.status_code == 200, f"Request {i+1} was blocked unexpectedly"


@pytest.mark.asyncio
async def test_register_rate_limit_blocks_after_exceeded(client: AsyncClient):
    """Registration should return 429 after 3 attempts per minute."""
    # Use up the 3 allowed attempts
    for i in range(3):
        email = f"ratelimit-regblock-{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )

    # 4th attempt should be blocked
    email = f"ratelimit-regblock-extra-{uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]


@pytest.mark.asyncio
async def test_magic_link_rate_limit_blocks_after_exceeded(client: AsyncClient):
    """Magic link should return 429 after 3 attempts per minute."""
    # Use up the 3 allowed attempts (they'll fail with email sending but still count)
    for i in range(3):
        email = f"ratelimit-magic-{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/magic-link",
            json={"email": email},
        )

    # 4th attempt should be blocked before even reaching the handler
    response = await client.post(
        "/api/auth/magic-link",
        json={"email": f"ratelimit-magic-extra-{uuid4().hex[:8]}@example.com"},
    )
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limits_are_per_endpoint(client: AsyncClient):
    """Rate limit for login should not affect register, and vice versa."""
    # Exhaust register limit (3 requests)
    for i in range(3):
        email = f"ratelimit-cross-reg-{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )

    # Login should still work (different rate limit key)
    response = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    # 401 means it got past rate limiting to the actual handler
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rate_limit_response_format(client: AsyncClient):
    """Verify the 429 response has the expected JSON structure."""
    # Exhaust register limit
    for i in range(3):
        email = f"ratelimit-format-{uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )

    response = await client.post(
        "/api/auth/register",
        json={"email": f"extra-{uuid4().hex[:8]}@example.com", "password": "password123"},
    )
    assert response.status_code == 429
    body = response.json()
    assert "detail" in body
    assert body["detail"] == "Too many requests. Please try again later."
