"""Direct tests for the second-brain Celery task wrappers.

The task bodies only run via ``.delay`` in production, so they need explicit
tests to cover the success + error + lock paths. We replace the inner async
function with a plain coroutine factory so ``asyncio.run`` consumes a real
(awaitable) coroutine — no orphaned-coroutine warnings — while the actual DB
work is stubbed out.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app.tasks import (
    comparison_generation,
    item_summary_generation,
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


def test_item_summary_task_retries_retryable_failure(monkeypatch) -> None:
    class RetrySentinelError(Exception):
        pass

    retryable_error = OperationalError("UPDATE items", {}, RuntimeError("database unavailable"))
    retry_calls: list[Exception] = []

    def fake_retry(*, exc: Exception):
        retry_calls.append(exc)
        raise RetrySentinelError

    with (
        patch.object(
            item_summary_generation,
            "_generate_item_summary",
            _coro_factory(raises=retryable_error),
        ),
        patch.object(item_summary_generation, "capture_sentry_exception") as cap,
    ):
        monkeypatch.setattr(item_summary_generation.generate_item_summary_task, "retry", fake_retry)
        with pytest.raises(RetrySentinelError):
            item_summary_generation.generate_item_summary_task(item_id="abc")

    assert retry_calls == [retryable_error]
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

