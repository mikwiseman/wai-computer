"""Tests for app/core/openai_client.py — singleton AsyncOpenAI factory."""

import openai
import pytest

import app.core.openai_client as openai_client_module
from app.config import Settings, get_settings
from app.core.openai_client import get_openai_client


@pytest.fixture(autouse=True)
def reset_openai_singleton(monkeypatch):
    """Reset the global _openai_client between tests and inject a fake key."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    openai_client_module._openai_client = None
    yield
    openai_client_module._openai_client = None
    get_settings.cache_clear()


def test_returns_async_openai_instance():
    client = get_openai_client()
    assert isinstance(client, openai.AsyncOpenAI)


def test_singleton_returns_same_instance():
    first = get_openai_client()
    second = get_openai_client()
    assert first is second


def test_settings_expose_openai_llm_model():
    settings = Settings()
    assert settings.openai_llm_model == "gpt-5.5"


def test_settings_expose_openai_embedding_model():
    settings = Settings()
    assert settings.openai_embedding_model == "text-embedding-3-large"
    assert settings.embedding_dimensions == 3072
