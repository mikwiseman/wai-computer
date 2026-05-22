"""Tests for auth endpoint rate limiting."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.rate_limit import RateLimiter, get_rate_limiter
from tests.conftest import LEGAL_ACCEPTANCE

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


class TestRateLimiterEdgeCases:
    """Edge case tests for the RateLimiter class."""

    def test_stale_keys_are_cleaned_up(self):
        """Keys with only expired timestamps should be removed during cleanup."""
        limiter = RateLimiter(cleanup_interval=10)

        with patch("app.core.rate_limit.time") as mock_time:
            # t=1000: create 50 unique keys
            mock_time.monotonic.return_value = 1000.0
            for i in range(50):
                limiter.check(f"stale_key_{i}", max_requests=10, window_seconds=60)
            assert limiter.key_count == 50

            # t=1070: all timestamps are expired, but cleanup hasn't run yet
            # (only 10s cleanup interval but we need a check() call to trigger it)
            mock_time.monotonic.return_value = 1070.0
            # Trigger a check that will also run cleanup (70s > 10s interval)
            limiter.check("fresh_key", max_requests=10, window_seconds=60)

            # All 50 stale keys should be purged, only fresh_key remains
            assert limiter.key_count == 1

    def test_empty_keys_removed_during_cleanup(self):
        """Keys whose timestamp lists are empty should be removed."""
        limiter = RateLimiter(cleanup_interval=5)

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter.check("key_a", max_requests=5, window_seconds=10)
            assert limiter.key_count == 1

            # Advance past window + cleanup interval
            mock_time.monotonic.return_value = 1020.0
            limiter.check("key_b", max_requests=5, window_seconds=10)
            # key_a should be cleaned up (timestamps expired)
            assert limiter.key_count == 1  # only key_b

    def test_rapid_requests_at_same_monotonic_time(self):
        """Multiple requests at the exact same timestamp should all be counted."""
        limiter = RateLimiter()

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 5000.0
            # 3 requests at the exact same time
            for _ in range(3):
                limiter.check("rapid", max_requests=3, window_seconds=60)

            # 4th request at the same time should be blocked
            with pytest.raises(HTTPException) as exc_info:
                limiter.check("rapid", max_requests=3, window_seconds=60)
            assert exc_info.value.status_code == 429

    def test_exact_boundary_timestamp_excluded(self):
        """A timestamp exactly at the cutoff boundary should be pruned (t > cutoff, not >=)."""
        limiter = RateLimiter()

        with patch("app.core.rate_limit.time") as mock_time:
            # Add a request at t=1000
            mock_time.monotonic.return_value = 1000.0
            limiter.check("boundary", max_requests=1, window_seconds=60)

            # At t=1060, cutoff = 1000.0, so timestamp 1000.0 is NOT > 1000.0
            # It should be pruned, allowing a new request
            mock_time.monotonic.return_value = 1060.0
            limiter.check("boundary", max_requests=1, window_seconds=60)

    def test_window_partially_expired(self):
        """Only expired timestamps should be pruned, recent ones kept."""
        limiter = RateLimiter()

        with patch("app.core.rate_limit.time") as mock_time:
            # 2 requests at t=1000
            mock_time.monotonic.return_value = 1000.0
            limiter.check("partial", max_requests=3, window_seconds=60)
            limiter.check("partial", max_requests=3, window_seconds=60)

            # 1 request at t=1050
            mock_time.monotonic.return_value = 1050.0
            limiter.check("partial", max_requests=3, window_seconds=60)

            # At t=1061: first 2 are expired, the one at t=1050 is still valid
            # So we have 1 existing + this new one = 2, under limit of 3
            mock_time.monotonic.return_value = 1061.0
            limiter.check("partial", max_requests=3, window_seconds=60)
            # One more should work (3rd)
            limiter.check("partial", max_requests=3, window_seconds=60)
            # 4th should fail (we now have: t=1050, t=1061, t=1061)
            with pytest.raises(HTTPException):
                limiter.check("partial", max_requests=3, window_seconds=60)

    def test_blocked_request_does_not_add_timestamp(self):
        """A rejected request should not record a timestamp (no penalty for being blocked)."""
        limiter = RateLimiter()

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(3):
                limiter.check("blocked", max_requests=3, window_seconds=60)

            # Multiple blocked attempts should not extend the lockout
            for _ in range(10):
                with pytest.raises(HTTPException):
                    limiter.check("blocked", max_requests=3, window_seconds=60)

            # After window expires, exactly 3 old timestamps should be pruned
            # (not 3 + 10 blocked attempts)
            mock_time.monotonic.return_value = 1061.0
            limiter.check("blocked", max_requests=3, window_seconds=60)

    def test_max_requests_of_one(self):
        """Rate limit of 1 request per window should work correctly."""
        limiter = RateLimiter()
        limiter.check("single", max_requests=1, window_seconds=60)

        with pytest.raises(HTTPException):
            limiter.check("single", max_requests=1, window_seconds=60)

    def test_very_short_window(self):
        """A 1-second window should correctly expire timestamps."""
        limiter = RateLimiter()

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter.check("short", max_requests=1, window_seconds=1)

            # 0.5 seconds later: still blocked
            mock_time.monotonic.return_value = 1000.5
            with pytest.raises(HTTPException):
                limiter.check("short", max_requests=1, window_seconds=1)

            # 1.01 seconds later: should work
            mock_time.monotonic.return_value = 1001.01
            limiter.check("short", max_requests=1, window_seconds=1)

    def test_reset_also_clears_max_window_and_cleanup_timer(self):
        """Reset should restore the limiter to a fully clean state."""
        limiter = RateLimiter(cleanup_interval=10)

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter.check("key", max_requests=5, window_seconds=300)

        assert limiter.key_count == 1
        assert limiter._max_window == 300
        assert limiter._last_cleanup is not None

        limiter.reset()

        assert limiter.key_count == 0
        assert limiter._max_window == 0
        assert limiter._last_cleanup is None

    def test_key_count_property(self):
        """key_count should accurately reflect tracked keys."""
        limiter = RateLimiter()
        assert limiter.key_count == 0

        limiter.check("a", max_requests=10, window_seconds=60)
        assert limiter.key_count == 1

        limiter.check("b", max_requests=10, window_seconds=60)
        assert limiter.key_count == 2

        limiter.check("a", max_requests=10, window_seconds=60)
        assert limiter.key_count == 2  # same key, no increase

    def test_cleanup_does_not_remove_active_keys(self):
        """Cleanup should preserve keys with recent timestamps."""
        limiter = RateLimiter(cleanup_interval=5)

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter.check("active", max_requests=5, window_seconds=60)
            limiter.check("stale", max_requests=5, window_seconds=60)

            # Advance 30s: both still within window, but cleanup runs
            mock_time.monotonic.return_value = 1030.0
            limiter.check("trigger", max_requests=5, window_seconds=60)

            # active and stale are still within their 60s window
            assert limiter.key_count == 3

    def test_cleanup_interval_respected(self):
        """Cleanup should not run more often than the configured interval."""
        limiter = RateLimiter(cleanup_interval=100)

        with patch("app.core.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter.check("old", max_requests=5, window_seconds=10)

            # 20s later: old key is expired but cleanup hasn't triggered
            # (cleanup_interval=100, only 20s elapsed)
            mock_time.monotonic.return_value = 1020.0
            limiter.check("new", max_requests=5, window_seconds=10)

            # old key still tracked (cleanup hasn't run)
            assert limiter.key_count == 2

            # 110s later: cleanup triggers
            mock_time.monotonic.return_value = 1110.0
            limiter.check("newest", max_requests=5, window_seconds=10)

            # old and new are both expired and cleaned up
            assert limiter.key_count == 1  # only "newest"


# --- Integration tests for rate-limited endpoints ---


@pytest.mark.asyncio
async def test_login_rate_limit_allows_normal_usage(client: AsyncClient):
    """Login should work normally within the rate limit."""
    # Register a user
    email = f"ratelimit-login-{uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
            json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
            json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
        )

    # 4th attempt should be blocked
    email = f"ratelimit-regblock-extra-{uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
            json={"email": email, **LEGAL_ACCEPTANCE},
        )

    # 4th attempt should be blocked before even reaching the handler
    response = await client.post(
        "/api/auth/magic-link",
        json={
            "email": f"ratelimit-magic-extra-{uuid4().hex[:8]}@example.com",
            **LEGAL_ACCEPTANCE,
        },
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
            json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
            json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
        )

    response = await client.post(
        "/api/auth/register",
        json={
            "email": f"extra-{uuid4().hex[:8]}@example.com",
            "password": "password123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code == 429
    body = response.json()
    assert "detail" in body
    assert body["detail"] == "Too many requests. Please try again later."
