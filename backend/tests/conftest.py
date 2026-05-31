"""Pytest configuration and fixtures."""

import asyncio
import os
from decimal import Decimal
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.rate_limit import get_rate_limiter
from app.db.session import get_db
from app.main import app
from app.models import Base
from app.models.billing import Plan

# Use PostgreSQL for tests (required for pgvector, JSONB, UUID)
# Set TEST_DATABASE_URL env var or use default test database
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/waicomputer_test"
)

LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


@pytest.fixture(autouse=True)
def _isolate_transcription_guard():
    """Back the Redis cost/abuse guard with a fresh fakeredis per test.

    The guard lazily builds a real async Redis client; without this it would (a)
    try to connect to a non-existent Redis on every guarded route (slow, flaky)
    and (b) cache an async client bound to one test's event loop, breaking the
    next test with 'Event loop is closed'. A fresh in-memory client per test is
    fast, deterministic, and isolated.
    """
    import fakeredis.aioredis

    from app.core import transcription_guard

    transcription_guard.set_redis_for_tests(
        fakeredis.aioredis.FakeRedis(decode_responses=True)
    )
    yield
    transcription_guard.set_redis_for_tests(None)


async def _seed_default_billing_plans(session: AsyncSession) -> None:
    """Mirror the billing migration seed for metadata-created test schemas."""
    session.add_all(
        [
            Plan(
                code="free",
                name="Free",
                description="3,000 transcribed words per week, 30-day memory window.",
                usd_amount_monthly=Decimal("0.00"),
                usd_amount_yearly=Decimal("0.00"),
                tinkoff_amount_rub_monthly=Decimal("0.00"),
                tinkoff_amount_rub_yearly=Decimal("0.00"),
                word_cap_per_week=3000,
                memory_retention_days=30,
                features={"agents": False, "mcp": False, "advanced_search": False},
            ),
            Plan(
                code="pro",
                name="Pro",
                description=(
                    "Unlimited transcription, permanent memory, agents, MCP, "
                    "advanced search."
                ),
                stripe_price_id_monthly="price_1TYUaVENNsR4WtAWrMI4kLWf",
                stripe_price_id_yearly="price_1TYUaWENNsR4WtAWRuIYlp7t",
                usd_amount_monthly=Decimal("12.00"),
                usd_amount_yearly=Decimal("96.00"),
                tinkoff_amount_rub_monthly=Decimal("999.00"),
                tinkoff_amount_rub_yearly=Decimal("7999.00"),
                word_cap_per_week=None,
                memory_retention_days=None,
                features={"agents": True, "mcp": True, "advanced_search": True},
            ),
        ]
    )
    await session.commit()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    schema_name = f"test_{uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

    async with admin_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema_name},public"}},
    )

    async with engine.begin() as conn:
        # Schema is freshly created above, so every table is new. Skip the
        # has_table() pre-check — under the test engine's search_path it can
        # falsely report existence and silently skip tables (observed: users,
        # recordings, segments, etc.), leaving the schema half-built.
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, checkfirst=False)
        )

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        await _seed_default_billing_plans(session)
        yield session

    await engine.dispose()
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
    await admin_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with overridden database."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Reset rate limiter state so tests don't interfere with each other
    get_rate_limiter().reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    get_rate_limiter().reset()


@pytest_asyncio.fixture(scope="function")
async def auth_headers(client: AsyncClient) -> dict:
    """Create a user and return auth headers."""
    email = f"testuser-{uuid4().hex}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}
