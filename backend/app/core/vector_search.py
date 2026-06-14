"""Postgres pgvector query-session tuning."""

from __future__ import annotations

from sqlalchemy import text


async def configure_vector_search(db) -> None:
    """Apply pgvector search parameters for the current transaction."""
    await db.execute(text("SET LOCAL ivfflat.probes = 20"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 80"))
