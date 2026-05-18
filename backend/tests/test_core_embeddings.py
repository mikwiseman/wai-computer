"""Tests for app/core/embeddings.py — OpenAI text-embedding-3-large wrappers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.core.openai_client as openai_client_module
from app.config import get_settings
from app.core.embeddings import (
    format_embedding,
    generate_embedding,
    generate_embeddings,
)


@pytest.fixture(autouse=True)
def mock_openai_client(monkeypatch):
    """Replace the singleton with a mock that returns canned embeddings."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock()
    openai_client_module._openai_client = mock_client
    yield mock_client
    openai_client_module._openai_client = None
    get_settings.cache_clear()


async def test_generate_embedding_calls_openai_with_model_and_dims(mock_openai_client):
    fake_embedding = [0.0] * 1536
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=fake_embedding)]
    )

    result = await generate_embedding("hello world")

    mock_openai_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-large",
        input="hello world",
        dimensions=1536,
    )
    assert result == fake_embedding
    assert len(result) == 1536


async def test_generate_embeddings_batches_multiple_texts(mock_openai_client):
    fake = [[0.1] * 1536, [0.2] * 1536]
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=fake[0]), MagicMock(embedding=fake[1])]
    )

    result = await generate_embeddings(["a", "b"])

    mock_openai_client.embeddings.create.assert_awaited_once_with(
        model="text-embedding-3-large",
        input=["a", "b"],
        dimensions=1536,
    )
    assert result == fake


def test_format_embedding_produces_postgres_vector_string():
    assert format_embedding([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


def test_format_embedding_empty_list():
    assert format_embedding([]) == "[]"
