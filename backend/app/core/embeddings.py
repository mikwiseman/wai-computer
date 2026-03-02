"""Embeddings generation using sentence-transformers."""

import asyncio
from functools import lru_cache

import numpy as np


class EmbeddingGenerator:
    """Generate embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the embedding generator.

        Args:
            model_name: Name of the sentence-transformers model.
                        all-MiniLM-L6-v2 produces 384-dimensional embeddings.
        """
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def generate_sync(self, text: str) -> list[float]:
        """
        Generate embedding for a single text synchronously.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        model = self._load_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def generate_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts synchronously.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings
        """
        model = self._load_model()
        embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [e.tolist() for e in embeddings]

    async def generate(self, text: str) -> list[float]:
        """
        Generate embedding for a single text asynchronously.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate_sync, text)

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts asynchronously.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate_batch_sync, texts)


# Global instance
_embedding_generator: EmbeddingGenerator | None = None


def get_embedding_generator(model_name: str = "all-MiniLM-L6-v2") -> EmbeddingGenerator:
    """Get or create the global embedding generator instance."""
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator(model_name)
    return _embedding_generator


async def generate_embedding(text: str) -> list[float]:
    """Convenience function to generate a single embedding."""
    generator = get_embedding_generator()
    return await generator.generate(text)


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Convenience function to generate multiple embeddings."""
    generator = get_embedding_generator()
    return await generator.generate_batch(texts)
