"""Tests for app/core/embeddings.py - Embedding generation via sentence-transformers."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import app.core.embeddings as embeddings_module
from app.core.embeddings import (
    EmbeddingGenerator,
    generate_embedding,
    generate_embeddings,
    get_embedding_generator,
)


@pytest.fixture(autouse=True)
def reset_embedding_singleton():
    """Reset the global _embedding_generator between tests."""
    embeddings_module._embedding_generator = None
    yield
    embeddings_module._embedding_generator = None


@pytest.fixture
def mock_model():
    """Create a mock SentenceTransformer model."""
    model = MagicMock()
    # Single text encode returns a 1D array of shape (384,)
    model.encode.return_value = np.random.rand(384).astype(np.float32)
    return model


@pytest.fixture
def generator_with_mock_model(mock_model):
    """Create an EmbeddingGenerator with a pre-injected mock model."""
    gen = EmbeddingGenerator(model_name="all-MiniLM-L6-v2")
    gen._model = mock_model
    return gen


class TestLoadModel:
    def test_first_call_creates_model(self):
        """First call to _load_model() imports and creates SentenceTransformer."""
        mock_st_class = MagicMock()
        mock_st_instance = MagicMock()
        mock_st_class.return_value = mock_st_instance

        gen = EmbeddingGenerator(model_name="all-MiniLM-L6-v2")
        assert gen._model is None

        with patch("app.core.embeddings.SentenceTransformer", mock_st_class, create=True), \
             patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=mock_st_class)}):
            # We need to clear the cached model and call _load_model
            # The module does a lazy import: from sentence_transformers import SentenceTransformer
            # We patch at the point of import inside _load_model
            with patch("sentence_transformers.SentenceTransformer", mock_st_class):
                model = gen._load_model()

        assert model is not None

    def test_second_call_returns_cached_model(self, mock_model):
        """Second call to _load_model() returns the same cached instance."""
        gen = EmbeddingGenerator()
        gen._model = mock_model

        first = gen._load_model()
        second = gen._load_model()

        assert first is second
        assert first is mock_model


class TestGenerateSync:
    def test_calls_encode_and_returns_list(self, generator_with_mock_model, mock_model):
        """generate_sync() calls model.encode() and returns .tolist() result."""
        expected_array = np.array([0.1, 0.2, 0.3] * 128, dtype=np.float32)
        mock_model.encode.return_value = expected_array

        result = generator_with_mock_model.generate_sync("Hello world")

        mock_model.encode.assert_called_once_with("Hello world", normalize_embeddings=True)
        assert isinstance(result, list)
        assert len(result) == 384
        assert result == expected_array.tolist()


class TestGenerateBatchSync:
    def test_encodes_multiple_texts(self, generator_with_mock_model, mock_model):
        """generate_batch_sync() encodes multiple texts and returns correct count."""
        texts = ["Hello", "World", "Test"]
        batch_result = np.random.rand(3, 384).astype(np.float32)
        mock_model.encode.return_value = batch_result

        results = generator_with_mock_model.generate_batch_sync(texts)

        mock_model.encode.assert_called_once_with(
            texts, normalize_embeddings=True, batch_size=32
        )
        assert len(results) == 3
        assert all(isinstance(r, list) for r in results)
        assert all(len(r) == 384 for r in results)


class TestAsyncWrappers:
    async def test_generate_delegates_to_generate_sync(
        self, generator_with_mock_model, mock_model
    ):
        """generate() async wrapper delegates to generate_sync."""
        expected_array = np.ones(384, dtype=np.float32)
        mock_model.encode.return_value = expected_array

        result = await generator_with_mock_model.generate("async text")

        mock_model.encode.assert_called_once_with("async text", normalize_embeddings=True)
        assert isinstance(result, list)
        assert len(result) == 384

    async def test_generate_batch_delegates_to_generate_batch_sync(
        self, generator_with_mock_model, mock_model
    ):
        """generate_batch() async wrapper delegates to generate_batch_sync."""
        texts = ["text1", "text2"]
        batch_result = np.random.rand(2, 384).astype(np.float32)
        mock_model.encode.return_value = batch_result

        results = await generator_with_mock_model.generate_batch(texts)

        mock_model.encode.assert_called_once_with(
            texts, normalize_embeddings=True, batch_size=32
        )
        assert len(results) == 2


class TestGetEmbeddingGenerator:
    def test_singleton_pattern(self):
        """get_embedding_generator() returns the same instance on repeated calls."""
        first = get_embedding_generator()
        second = get_embedding_generator()

        assert first is second
        assert isinstance(first, EmbeddingGenerator)

    def test_uses_specified_model_name(self):
        """get_embedding_generator() uses the model name passed on first call."""
        gen = get_embedding_generator("all-MiniLM-L6-v2")
        assert gen.model_name == "all-MiniLM-L6-v2"


class TestConvenienceFunctions:
    async def test_generate_embedding_uses_singleton(self, mock_model):
        """generate_embedding() convenience function uses the global generator."""
        expected_array = np.ones(384, dtype=np.float32)
        mock_model.encode.return_value = expected_array

        # Pre-set the singleton with our mock
        gen = get_embedding_generator()
        gen._model = mock_model

        result = await generate_embedding("test text")

        assert isinstance(result, list)
        assert len(result) == 384
        mock_model.encode.assert_called_once_with("test text", normalize_embeddings=True)

    async def test_generate_embeddings_uses_singleton(self, mock_model):
        """generate_embeddings() convenience function uses the global generator."""
        batch_result = np.random.rand(2, 384).astype(np.float32)
        mock_model.encode.return_value = batch_result

        gen = get_embedding_generator()
        gen._model = mock_model

        results = await generate_embeddings(["text1", "text2"])

        assert len(results) == 2
        mock_model.encode.assert_called_once_with(
            ["text1", "text2"], normalize_embeddings=True, batch_size=32
        )
