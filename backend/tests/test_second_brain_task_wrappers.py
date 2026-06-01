"""Direct tests for the second-brain Celery task wrappers.

The task bodies only run via ``.delay`` in production, so they need explicit
tests to cover the success + error + lock paths. We replace the inner async
function with a plain coroutine factory so ``asyncio.run`` consumes a real
(awaitable) coroutine — no orphaned-coroutine warnings — while the actual DB
work is stubbed out.
"""

from unittest.mock import patch

import pytest

from app.tasks import (
    comparison_generation,
    item_summary_generation,
    mcp_sync,
)


def _coro_factory(*, raises: Exception | None = None, returns=None):
    """Return an async function usable as a drop-in for an inner _coro."""

    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises
        return returns

    return _inner


def test_item_summary_task_success() -> None:
    with patch.object(item_summary_generation, "_generate_item_summary", _coro_factory()):
        item_summary_generation.generate_item_summary_task(item_id="abc")


def test_item_summary_task_reraises_and_captures() -> None:
    with (
        patch.object(
            item_summary_generation,
            "_generate_item_summary",
            _coro_factory(raises=RuntimeError("boom")),
        ),
        patch.object(item_summary_generation, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(RuntimeError):
            item_summary_generation.generate_item_summary_task(item_id="abc")
    cap.assert_called_once()


def test_comparison_task_success() -> None:
    with patch.object(comparison_generation, "_generate", _coro_factory()):
        comparison_generation.generate_comparison_task(comparison_id="c1", intent="x")


def test_comparison_task_reraises_and_captures() -> None:
    with (
        patch.object(comparison_generation, "_generate", _coro_factory(raises=ValueError("nope"))),
        patch.object(comparison_generation, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(ValueError):
            comparison_generation.generate_comparison_task(comparison_id="c1")
    cap.assert_called_once()


class _FakeRedis:
    def __init__(self, acquire: bool = True):
        self._acquire = acquire
        self.deleted: list[str] = []

    def set(self, key, val, nx=False, ex=None):
        return self._acquire

    def delete(self, key):
        self.deleted.append(key)


def test_mcp_sync_task_acquires_lock_and_runs() -> None:
    fake = _FakeRedis(acquire=True)
    with (
        patch.object(mcp_sync, "_redis_client", return_value=fake),
        patch.object(mcp_sync, "_sync_one", _coro_factory()),
    ):
        mcp_sync.sync_mcp_connection(connection_id="conn1")
    assert fake.deleted == ["mcp_sync_lock:conn1"]


def test_mcp_sync_task_skips_when_lock_held() -> None:
    held = _FakeRedis(acquire=False)
    sentinel = {"ran": False}

    async def _should_not_run(*a, **k):
        sentinel["ran"] = True

    with (
        patch.object(mcp_sync, "_redis_client", return_value=held),
        patch.object(mcp_sync, "_sync_one", _should_not_run),
    ):
        mcp_sync.sync_mcp_connection(connection_id="conn1")
    assert sentinel["ran"] is False


def test_mcp_sync_task_runs_without_redis() -> None:
    with (
        patch.object(mcp_sync, "_redis_client", return_value=None),
        patch.object(mcp_sync, "_sync_one", _coro_factory()),
    ):
        mcp_sync.sync_mcp_connection(connection_id="conn1")


def test_mcp_sync_task_reraises_and_releases_lock_on_error() -> None:
    fake = _FakeRedis(acquire=True)
    with (
        patch.object(mcp_sync, "_redis_client", return_value=fake),
        patch.object(mcp_sync, "_sync_one", _coro_factory(raises=RuntimeError("sync failed"))),
        patch.object(mcp_sync, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(RuntimeError):
            mcp_sync.sync_mcp_connection(connection_id="conn1")
    cap.assert_called_once()
    assert fake.deleted == ["mcp_sync_lock:conn1"]


def test_dispatch_due_task_wrapper() -> None:
    with patch.object(mcp_sync, "_dispatch_due", _coro_factory(returns=3)):
        assert mcp_sync.dispatch_due_mcp_syncs() == 3
