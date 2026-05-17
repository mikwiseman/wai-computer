"""Pytest configuration and fixtures."""

import asyncio
import os
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

# Use PostgreSQL for tests (required for pgvector, JSONB, UUID)
# Set TEST_DATABASE_URL env var or use default test database
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/waicomputer_test"
)


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
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
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
        json={"email": email, "password": "testpassword123"},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}
