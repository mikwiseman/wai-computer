"""Embeddings via OpenAI text-embedding-3-large."""

import logging
import time

from app.config import get_settings
from app.core.observability import fingerprint_text
from app.core.openai_client import get_openai_client

logger = logging.getLogger(__name__)


async def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding for the given text."""
    settings = get_settings()
    client = get_openai_client()
    started = time.perf_counter()
    try:
        response = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
            dimensions=settings.embedding_dimensions,
        )
    except Exception as exc:
        logger.warning(
            "embedding generation failed input_count=1 model=%s dimensions=%s latency_ms=%s "
            "error_type=%s error_fingerprint=%s",
            settings.openai_embedding_model,
            settings.embedding_dimensions,
            round((time.perf_counter() - started) * 1000),
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise
    usage = getattr(response, "usage", None)
    logger.info(
        "embedding generation completed input_count=1 model=%s dimensions=%s latency_ms=%s "
        "prompt_tokens=%s total_tokens=%s",
        settings.openai_embedding_model,
        settings.embedding_dimensions,
        round((time.perf_counter() - started) * 1000),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "total_tokens", None),
    )
    return list(response.data[0].embedding)


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single OpenAI request."""
    settings = get_settings()
    client = get_openai_client()
    started = time.perf_counter()
    try:
        response = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
            dimensions=settings.embedding_dimensions,
        )
    except Exception as exc:
        logger.warning(
            "embedding generation failed input_count=%s model=%s dimensions=%s latency_ms=%s "
            "error_type=%s error_fingerprint=%s",
            len(texts),
            settings.openai_embedding_model,
            settings.embedding_dimensions,
            round((time.perf_counter() - started) * 1000),
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise
    usage = getattr(response, "usage", None)
    logger.info(
        "embedding generation completed input_count=%s model=%s dimensions=%s latency_ms=%s "
        "prompt_tokens=%s total_tokens=%s",
        len(texts),
        settings.openai_embedding_model,
        settings.embedding_dimensions,
        round((time.perf_counter() - started) * 1000),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "total_tokens", None),
    )
    return [list(item.embedding) for item in response.data]


def format_embedding(embedding: list[float]) -> str:
    """Format an embedding list as a PostgreSQL vector string.

    Produces ``[0.1,0.2,0.3]`` suitable for ``CAST(:embedding AS vector)``.
    """
    return "[" + ",".join(str(x) for x in embedding) + "]"
