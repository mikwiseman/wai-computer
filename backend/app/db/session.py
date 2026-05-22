"""Database session configuration."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

_engine = None
_session_maker = None
_runtime_pid: int | None = None
_runtime_loop_id: int | None = None


def _create_engine():
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=2,
        pool_recycle=1800,
    )


def _current_loop_id() -> int | None:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return None


def _ensure_runtime(force: bool = False) -> None:
    global _engine, _session_maker, _runtime_pid, _runtime_loop_id

    current_pid = os.getpid()
    current_loop_id = _current_loop_id()
    runtime_ready = (
        _engine is not None
        and _session_maker is not None
        and _runtime_pid == current_pid
        and _runtime_loop_id == current_loop_id
    )
    if not force and runtime_ready:
        return

    if _engine is not None:
        _engine.sync_engine.dispose()

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
    _runtime_loop_id = current_loop_id


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
