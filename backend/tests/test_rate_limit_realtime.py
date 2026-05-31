"""Tests for realtime session-mint rate-limit guardrails."""

import pytest
from fastapi import HTTPException

from app.core.rate_limit import (
    REALTIME_MINT_BURST_MAX,
    check_realtime_session_mint_rate_limit,
    get_rate_limiter,
)


@pytest.fixture(autouse=True)
def _reset_limiter():
    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()


def test_burst_blocks_absurd_mint_rate():
    for _ in range(REALTIME_MINT_BURST_MAX):
        check_realtime_session_mint_rate_limit("user-1", "dictation")
    with pytest.raises(HTTPException) as exc:
        check_realtime_session_mint_rate_limit("user-1", "dictation")
    assert exc.value.status_code == 429


def test_returns_recent_mint_count_for_alerting():
    counts = [
        check_realtime_session_mint_rate_limit("user-2", "recording") for _ in range(3)
    ]
    assert counts == [1, 2, 3]


def test_burst_cap_is_per_user():
    for _ in range(REALTIME_MINT_BURST_MAX):
        check_realtime_session_mint_rate_limit("user-a", "dictation")
    # A different user is unaffected by user-a hitting the burst cap.
    assert check_realtime_session_mint_rate_limit("user-b", "dictation") == 1


def test_daily_cap_is_per_purpose():
    # Dictation has a tighter daily cap than recording; recording is not blocked
    # by exhausting the dictation budget (they use separate keys).
    from app.core.rate_limit import REALTIME_MINT_DAILY_MAX

    limiter = get_rate_limiter()
    # Pre-fill the dictation daily key to its cap for this user.
    for _ in range(REALTIME_MINT_DAILY_MAX["dictation"]):
        limiter.check(
            key="rt_mint_daily:dictation:user-3",
            max_requests=REALTIME_MINT_DAILY_MAX["dictation"] + 1,
            window_seconds=86_400,
        )
    with pytest.raises(HTTPException):
        check_realtime_session_mint_rate_limit("user-3", "dictation")
    # Recording for the same user still works (separate, larger budget).
    assert check_realtime_session_mint_rate_limit("user-3", "recording") == 1
