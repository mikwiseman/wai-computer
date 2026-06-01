"""Tests for the Redis-backed Deepgram cost/abuse guard.

Uses fakeredis for the happy paths and a deliberately broken client to prove the
FAIL-OPEN contract: a Redis outage must never block transcription.
"""

import fakeredis.aioredis
import pytest
from redis.exceptions import RedisError

from app.config import get_settings
from app.core import transcription_guard as guard
from app.core.transcription_guard import TranscriptionGuardError


@pytest.fixture
def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    guard.set_redis_for_tests(client)
    yield client
    guard.set_redis_for_tests(None)


@pytest.fixture
def settings():
    return get_settings()


# --- kill switch --------------------------------------------------------------
async def test_halted_follows_env(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_enabled", True)
    assert await guard.transcription_halted() is False
    monkeypatch.setattr(settings, "transcription_enabled", False)
    assert await guard.transcription_halted() is True


async def test_halted_via_runtime_redis_flag(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_enabled", True)
    assert await guard.transcription_halted() is False
    await fake_redis.set("dg:killswitch", "1")
    assert await guard.transcription_halted() is True
    await fake_redis.delete("dg:killswitch")
    assert await guard.transcription_halted() is False


# --- mint rate guard ----------------------------------------------------------
async def test_mint_burst_hard_cap(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_mint_burst_max", 3)
    monkeypatch.setattr(settings, "realtime_mint_daily_max_dictation", 10_000)
    for _ in range(3):
        await guard.register_mint("u1", "dictation")
    with pytest.raises(TranscriptionGuardError) as ei:
        await guard.register_mint("u1", "dictation")
    assert ei.value.code == "mint_burst"


async def test_mint_daily_backstop(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_mint_burst_max", 10_000)
    monkeypatch.setattr(settings, "realtime_mint_daily_max_recording", 2)
    await guard.register_mint("u2", "recording")
    await guard.register_mint("u2", "recording")
    with pytest.raises(TranscriptionGuardError) as ei:
        await guard.register_mint("u2", "recording")
    assert ei.value.code == "mint_daily"


async def test_mint_returns_sustained_count(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_mint_burst_max", 10_000)
    monkeypatch.setattr(settings, "realtime_mint_daily_max_dictation", 10_000)
    counts = [await guard.register_mint("u3", "dictation") for _ in range(3)]
    assert counts == [1, 2, 3]


# --- daily audio-minute ceilings ---------------------------------------------
async def test_global_minutes_ceiling(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_abuse_caps_enabled", True)
    monkeypatch.setattr(settings, "deepgram_global_daily_minutes_cap", 10)
    monkeypatch.setattr(settings, "deepgram_user_daily_minutes_cap", 0)
    await guard.check_minutes_budget("u4", 5)  # under cap -> ok
    await guard.record_minutes("u4", 9)
    await guard.check_minutes_budget("u4", 0.5)  # 9 + 0.5 <= 10 -> ok
    with pytest.raises(TranscriptionGuardError) as ei:
        await guard.check_minutes_budget("u4", 2)  # 9 + 2 > 10
    assert ei.value.code == "global_minutes"


async def test_per_user_minutes_ceiling(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_abuse_caps_enabled", True)
    monkeypatch.setattr(settings, "deepgram_global_daily_minutes_cap", 0)
    monkeypatch.setattr(settings, "deepgram_user_daily_minutes_cap", 5)
    await guard.record_minutes("ua", 5)
    with pytest.raises(TranscriptionGuardError) as ei:
        await guard.check_minutes_budget("ua", 0.1)
    assert ei.value.code == "user_minutes"
    await guard.check_minutes_budget("ub", 1)  # a different user is unaffected


async def test_minutes_caps_disabled(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_abuse_caps_enabled", False)
    monkeypatch.setattr(settings, "deepgram_global_daily_minutes_cap", 1)
    await guard.record_minutes("uc", 100)
    await guard.check_minutes_budget("uc", 100)  # must not raise


# --- concurrent stream lease --------------------------------------------------
async def test_stream_slot_per_user_cap(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_per_user", 2)
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_global", 100)
    t1 = await guard.acquire_stream_slot("u5", lease_ttl_seconds=60)
    t2 = await guard.acquire_stream_slot("u5", lease_ttl_seconds=60)
    assert t1 and t2
    assert await guard.acquire_stream_slot("u5", lease_ttl_seconds=60) is None
    await guard.release_stream_slot("u5", t1)
    assert await guard.acquire_stream_slot("u5", lease_ttl_seconds=60) is not None


async def test_stream_slot_global_cap(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_per_user", 100)
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_global", 2)
    assert await guard.acquire_stream_slot("ua", lease_ttl_seconds=60)
    assert await guard.acquire_stream_slot("ub", lease_ttl_seconds=60)
    assert await guard.acquire_stream_slot("uc", lease_ttl_seconds=60) is None


# --- circuit breaker ----------------------------------------------------------
async def test_breaker_opens_immediately_on_402(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "deepgram_breaker_failure_threshold", 5)
    assert await guard.provider_breaker_open() is False
    await guard.record_provider_result(success=False, status_code=402)
    assert await guard.provider_breaker_open() is True
    await guard.record_provider_result(success=True)  # success closes it
    assert await guard.provider_breaker_open() is False


async def test_breaker_opens_on_failure_streak(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "deepgram_breaker_failure_threshold", 3)
    await guard.record_provider_result(success=False, status_code=500)
    await guard.record_provider_result(success=False, status_code=500)
    assert await guard.provider_breaker_open() is False
    await guard.record_provider_result(success=False, status_code=503)
    assert await guard.provider_breaker_open() is True


# --- fail-open contract -------------------------------------------------------
async def test_all_guards_fail_open_on_redis_error(settings, monkeypatch):
    class _BrokenPipe:
        def __getattr__(self, _name):
            def _chain(*_a, **_k):
                return self

            return _chain

        async def execute(self):
            raise RedisError("boom")

    class _BrokenRedis:
        def pipeline(self):
            return _BrokenPipe()

        async def exists(self, *_a):
            raise RedisError("boom")

        async def set(self, *_a, **_k):
            raise RedisError("boom")

        async def delete(self, *_a):
            raise RedisError("boom")

    guard.set_redis_for_tests(_BrokenRedis())
    monkeypatch.setattr(settings, "transcription_enabled", True)
    try:
        assert await guard.transcription_halted() is False
        assert await guard.register_mint("z", "dictation") == 0
        await guard.check_minutes_budget("z", 9999)  # must not raise
        assert await guard.acquire_stream_slot("z", lease_ttl_seconds=60) is not None
        assert await guard.provider_breaker_open() is False
        await guard.record_provider_result(success=False, status_code=402)  # must not raise
        await guard.record_provider_result(success=True)  # must not raise
        await guard.record_provider_result(success=False, status_code=500)  # streak path
        await guard.release_stream_slot("z", "tok")  # must not raise
        await guard.record_minutes("z", 1.0)  # must not raise
    finally:
        guard.set_redis_for_tests(None)


async def test_get_redis_lazily_builds_and_caches_a_client():
    guard.set_redis_for_tests(None)
    try:
        client = guard.get_redis()  # builds from settings.redis_url (no connection yet)
        assert client is not None
        assert guard.get_redis() is client  # cached singleton
    finally:
        guard.set_redis_for_tests(None)


# --- disabled / zero-cap early returns (coverage of the no-op branches) -------
async def test_minutes_budget_noop_when_both_caps_zero(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "transcription_abuse_caps_enabled", True)
    monkeypatch.setattr(settings, "deepgram_global_daily_minutes_cap", 0)
    monkeypatch.setattr(settings, "deepgram_user_daily_minutes_cap", 0)
    await guard.check_minutes_budget("u", 10_000)  # both caps 0 -> early return, no raise


async def test_record_minutes_noop_for_nonpositive(fake_redis):
    await guard.record_minutes("u", 0)  # <= 0 -> early return
    await guard.record_minutes("u", -5)


async def test_stream_slot_unlimited_when_caps_zero(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_per_user", 0)
    monkeypatch.setattr(settings, "realtime_max_concurrent_streams_global", 0)
    token = await guard.acquire_stream_slot("u", lease_ttl_seconds=60)
    assert token is not None  # both caps 0 -> always grant a token


async def test_release_stream_slot_noop_without_token(fake_redis):
    await guard.release_stream_slot("u", None)  # None -> early return


async def test_breaker_disabled_when_threshold_zero(settings, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "deepgram_breaker_failure_threshold", 0)
    await guard.record_provider_result(success=False, status_code=402)
    assert await guard.provider_breaker_open() is False  # disabled -> never opens
