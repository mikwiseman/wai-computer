"""Database session configuration."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

_engine = None
_session_maker = None
_runtime_pid: int | None = None
# Celery workers run each task in its OWN asyncio.run() loop. A pooled asyncpg
# connection returned after one task is later closed during the next task's
# engine teardown — from a different, already-closed loop — raising
# "MissingGreenlet ... Exception closing connection" (recover_stale every
# minute was the visible spammer). NullPool opens+closes a connection per use,
# always inside the current loop, so nothing survives the loop boundary. The API
# keeps real pooling (it runs on one long-lived loop). Toggled per process via
# enable_nullpool() from the Celery worker_process_init hook.
_use_nullpool = False
# The event LOOP OBJECT the runtime is bound to — NOT id(loop). A Celery task
# that wraps each run in asyncio.run() gets a fresh loop that is closed and
# GC'd afterwards; CPython then reuses that freed address, so the next loop can
# carry the SAME id(). Tracking by id() therefore let _ensure_runtime believe a
# stale engine (bound to the closed loop) was still current and reuse it —
# raising "MissingGreenlet: greenlet_spawn has not been called" on the next DB
# call (recover_stale_recording_processing, every minute). Holding the object
# makes the identity check exact AND pins its address so it cannot be recycled.
_runtime_loop = None


def _create_engine():
    if _use_nullpool:
        # No cross-call pooling: each connection lives and dies within one
        # asyncio.run() loop, so it can never be closed from a dead loop.
        return create_async_engine(
            settings.database_url,
            echo=settings.debug,
            poolclass=NullPool,
        )
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=2,
        pool_recycle=1800,
    )


def _current_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _ensure_runtime(force: bool = False) -> None:
    global _engine, _session_maker, _runtime_pid, _runtime_loop

    current_pid = os.getpid()
    current_loop = _current_loop()
    runtime_ready = (
        _engine is not None
        and _session_maker is not None
        and _runtime_pid == current_pid
        and _runtime_loop is current_loop
    )
    if not force and runtime_ready:
        return

    if _engine is not None:
        # The previous engine may be bound to a now-closed loop; disposing its
        # pool from a different loop can raise. Never let that abort the rebuild
        # (otherwise the runtime stays broken and every call keeps failing).
        try:
            _engine.sync_engine.dispose()
        except Exception:  # noqa: BLE001 - best-effort teardown of a stale engine
            pass

    engine = _create_engine()
    _engine = engine
    _session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    _runtime_pid = current_pid
    _runtime_loop = current_loop


class _AsyncSessionMakerProxy:
    def __call__(self, *args, **kwargs):
        _ensure_runtime()
        return _session_maker(*args, **kwargs)


class _EngineProxy:
    def __getattr__(self, name: str):
        _ensure_runtime()
        return getattr(_engine, name)


def reset_db_runtime() -> None:
    """Recreate the async engine/session factory for the current process."""
    _ensure_runtime(force=True)


def enable_nullpool() -> None:
    """Switch this process to NullPool and rebuild the runtime.

    Called from the Celery worker_process_init hook: a worker runs each task in
    its own ``asyncio.run()`` loop, so a pooled connection would eventually be
    closed from a dead loop (MissingGreenlet). NullPool sidesteps that entirely.
    """
    global _use_nullpool
    _use_nullpool = True
    reset_db_runtime()


async_session_maker = _AsyncSessionMakerProxy()
engine = _EngineProxy()

_ensure_runtime()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Standalone DB session context manager for use outside FastAPI (e.g., Celery tasks)."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
