"""Singleton AsyncOpenAI client used by Companion, summarization, and embeddings."""

import openai

from app.config import get_settings

_openai_client: openai.AsyncOpenAI | None = None


def get_openai_client() -> openai.AsyncOpenAI:
    """Return a process-wide AsyncOpenAI client configured from settings."""
    global _openai_client
    if _openai_client is None:
        settings = get_settings()
        _openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client
