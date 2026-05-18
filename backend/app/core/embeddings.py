"""Embeddings via OpenAI text-embedding-3-large."""

from app.config import get_settings
from app.core.openai_client import get_openai_client


async def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding for the given text."""
    settings = get_settings()
    client = get_openai_client()
    response = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
        dimensions=settings.embedding_dimensions,
    )
    return list(response.data[0].embedding)


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single OpenAI request."""
    settings = get_settings()
    client = get_openai_client()
    response = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [list(item.embedding) for item in response.data]


def format_embedding(embedding: list[float]) -> str:
    """Format an embedding list as a PostgreSQL vector string.

    Produces ``[0.1,0.2,0.3]`` suitable for ``CAST(:embedding AS vector)``.
    """
    return "[" + ",".join(str(x) for x in embedding) + "]"
