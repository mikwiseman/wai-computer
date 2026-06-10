"""Regression tests for the two prod Celery failures found 2026-06-01.

1. Beat scheduled a task whose module was missing from
   ``celery_app.conf.imports`` → the task was never registered
   → ``KeyError`` on every scheduled dispatch.
2. ``app.db.session`` tracked the event loop by ``id(loop)``. CPython recycles a
   freed loop's address, so a Celery task wrapping each run in ``asyncio.run()``
   (e.g. ``recover_stale_recording_processing``, every minute) could get a new
   loop with the same id() and reuse an engine bound to the CLOSED loop →
   ``MissingGreenlet: greenlet_spawn has not been called``.
"""

import asyncio


def test_every_beat_scheduled_task_is_registered():
    """Guard against beat entries that reference an unimported task module."""
    from app.tasks.celery_app import celery_app

    celery_app.loader.import_default_modules()  # what the worker does on boot
    registered = set(celery_app.tasks)
    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    missing = sorted(scheduled - registered)
    assert not missing, (
        "beat references tasks that aren't registered — add their module to "
        f"celery_app.conf.imports: {missing}"
    )


def test_summary_audio_generation_task_registered():
    from app.tasks.celery_app import celery_app

    celery_app.loader.import_default_modules()
    assert "app.tasks.summary_audio_generation.generate_summary_audio" in celery_app.tasks


def test_worker_runtime_uses_nullpool_api_keeps_pooling():
    """The Celery worker switches to NullPool (no connection survives a task's
    asyncio.run() loop → no cross-loop close → no MissingGreenlet). The default
    (API) process keeps real pooling."""
    from app.db import session as s

    try:
        s._use_nullpool = False
        s.reset_db_runtime()
        assert type(s._engine.sync_engine.pool).__name__ != "NullPool"

        s.enable_nullpool()
        assert type(s._engine.sync_engine.pool).__name__ == "NullPool"
    finally:
        # Restore the default so global state doesn't leak into other tests.
        s._use_nullpool = False
        s.reset_db_runtime()


def test_db_runtime_rebuilt_per_event_loop():
    """A fresh asyncio.run() loop must get a fresh engine, never a stale one
    bound to a previous (closed) loop — even if CPython recycles the loop id."""
    from app.db import session as s

    async def _grab():
        s._ensure_runtime()
        return s._engine

    e1 = asyncio.run(_grab())
    e2 = asyncio.run(_grab())
    # Hold both objects so identity comparison is reliable (no address reuse).
    assert e1 is not e2, (
        "engine was not rebuilt across asyncio.run() boundaries — id()-based "
        "loop tracking reused an engine bound to a closed loop"
    )
