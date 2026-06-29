"""Tests for at-rest secret encryption helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import secrets_crypto


@pytest.fixture(autouse=True)
def clear_fernet_cache() -> None:
    secrets_crypto._fernet.cache_clear()
    yield
    secrets_crypto._fernet.cache_clear()


def test_encrypt_secret_round_trips_with_configured_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        secrets_crypto,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret="test-secret"),
    )

    token = secrets_crypto.encrypt_secret("oauth-token")

    assert token != "oauth-token"
    assert secrets_crypto.decrypt_secret(token) == "oauth-token"


def test_decrypt_secret_rejects_tampered_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        secrets_crypto,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret="test-secret"),
    )

    with pytest.raises(secrets_crypto.SecretDecryptError):
        secrets_crypto.decrypt_secret("not-a-fernet-token")


def test_decrypt_secret_rejects_tokens_after_secret_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        secrets_crypto,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret="old-secret"),
    )
    token = secrets_crypto.encrypt_secret("oauth-token")

    secrets_crypto._fernet.cache_clear()
    monkeypatch.setattr(
        secrets_crypto,
        "get_settings",
        lambda: SimpleNamespace(jwt_secret="new-secret"),
    )

    with pytest.raises(secrets_crypto.SecretDecryptError):
        secrets_crypto.decrypt_secret(token)
