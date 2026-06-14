from __future__ import annotations

import pytest

from app.core.vector_search import configure_vector_search


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))


@pytest.mark.asyncio
async def test_configure_vector_search_sets_pgvector_query_parameters() -> None:
    session = FakeSession()

    await configure_vector_search(session)

    assert session.statements == [
        "SET LOCAL ivfflat.probes = 20",
        "SET LOCAL hnsw.ef_search = 80",
    ]
