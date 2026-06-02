"""Working-agents cost/abuse guard (P6) — caps enforced, and FAIL OPEN on a
Redis outage (the approval gate is the fail-closed net, so a permissive cost
guard is correct)."""

import fakeredis.aioredis
import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from app.config import get_settings
from app.core import agent_guard
from app.core.agent_guard import AgentGuardError

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis():
    agent_guard.set_redis_for_tests(
        fakeredis.aioredis.FakeRedis(decode_responses=True)
    )
    yield
    agent_guard.set_redis_for_tests(None)


class _BrokenRedis:
    """Models a Redis outage: queued pipeline ops are no-ops, every round-trip raises."""

    def pipeline(self):
        return self

    def __getattr__(self, _name):
        def _queued(*_a, **_k):
            return self

        return _queued

    async def execute(self):
        raise RedisError("redis down")

    async def exists(self, *_a, **_k):
        raise RedisError("redis down")


# --- kill-switch -------------------------------------------------------------


async def test_killswitch_off_then_on() -> None:
    assert await agent_guard.agents_halted() is False
    await agent_guard.get_redis().set("agents:killswitch", "1")
    assert await agent_guard.agents_halted() is True


async def test_agents_disabled_env_halts(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agents_enabled", False)
    assert await agent_guard.agents_halted() is True


async def test_killswitch_fails_open_on_redis_error() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    # A blip must not silently halt a healthy fleet.
    assert await agent_guard.agents_halted() is False


# --- daily run ceilings ------------------------------------------------------


async def test_check_run_budget_allows_under_cap(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_user_daily_runs_cap", 5)
    await agent_guard.record_run("u1")
    await agent_guard.check_run_budget("u1")  # 1 < 5 → no raise


async def test_check_run_budget_raises_over_user_cap(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_user_daily_runs_cap", 2)
    monkeypatch.setattr(get_settings(), "agent_global_daily_runs_cap", 0)
    for _ in range(2):
        await agent_guard.record_run("u1")
    with pytest.raises(AgentGuardError) as ei:
        await agent_guard.check_run_budget("u1")
    assert ei.value.code == "user_runs"
    assert ei.value.retry_after == 3600


async def test_check_run_budget_raises_over_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_user_daily_runs_cap", 0)
    monkeypatch.setattr(get_settings(), "agent_global_daily_runs_cap", 1)
    await agent_guard.record_run("whoever")
    with pytest.raises(AgentGuardError) as ei:
        await agent_guard.check_run_budget("someone-else")  # global is shared
    assert ei.value.code == "global_runs"


async def test_check_run_budget_noop_when_caps_disabled(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_abuse_caps_enabled", False)
    for _ in range(50):
        await agent_guard.record_run("u1")
    await agent_guard.check_run_budget("u1")  # disabled → never raises


async def test_check_run_budget_fails_open_on_redis_error() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    await agent_guard.check_run_budget("u1")  # no raise — allow through


async def test_record_run_increments_counters() -> None:
    await agent_guard.record_run("u1")
    await agent_guard.record_run("u1")
    key = f"agents:runs:user:u1:{agent_guard._today()}"
    assert int(await agent_guard.get_redis().get(key)) == 2


# --- concurrency lease -------------------------------------------------------


async def test_acquire_run_slot_respects_per_user_cap(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_per_user", 1)
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_global", 100)
    first = await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300)
    assert first is not None
    second = await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300)
    assert second is None  # at the per-user cap


async def test_release_run_slot_frees_a_slot(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_per_user", 1)
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_global", 100)
    token = await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300)
    assert token is not None
    assert await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300) is None
    await agent_guard.release_run_slot("u1", token)
    assert await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300) is not None


async def test_acquire_run_slot_fails_open_on_redis_error() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    token = await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300)
    assert token  # a Redis outage must not block runs


async def test_acquire_run_slot_respects_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_per_user", 100)
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_global", 1)
    assert await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300) is not None
    assert await agent_guard.acquire_run_slot("u2", lease_ttl_seconds=300) is None


async def test_acquire_run_slot_returns_token_when_caps_disabled(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_per_user", 0)
    monkeypatch.setattr(get_settings(), "agent_max_concurrent_runs_global", 0)
    assert await agent_guard.acquire_run_slot("u1", lease_ttl_seconds=300)


async def test_check_run_budget_noop_when_both_caps_zero(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_user_daily_runs_cap", 0)
    monkeypatch.setattr(get_settings(), "agent_global_daily_runs_cap", 0)
    await agent_guard.check_run_budget("u1")  # both 0 → no-op, no raise


async def test_record_run_fails_open_on_redis_error() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    await agent_guard.record_run("u1")  # swallow the outage, never raise


async def test_release_run_slot_ignores_missing_token() -> None:
    await agent_guard.release_run_slot("u1", None)  # no token → no-op


async def test_release_run_slot_fails_open_on_redis_error() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    await agent_guard.release_run_slot("u1", "tok")  # swallow the outage


async def test_degraded_alert_is_throttled() -> None:
    agent_guard.set_redis_for_tests(_BrokenRedis())
    # First degradation emits, the immediate second is throttled — neither raises.
    assert await agent_guard.agents_halted() is False
    assert await agent_guard.agents_halted() is False


async def test_get_redis_builds_and_caches_client(monkeypatch) -> None:
    agent_guard.set_redis_for_tests(None)  # force a rebuild
    sentinel = object()
    calls = {"n": 0}

    def fake_from_url(*_a, **_k):
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(agent_guard.aioredis, "from_url", fake_from_url)
    assert agent_guard.get_redis() is sentinel
    assert agent_guard.get_redis() is sentinel  # cached
    assert calls["n"] == 1
    agent_guard.set_redis_for_tests(None)
