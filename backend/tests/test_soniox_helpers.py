"""Additional unit tests for app.core.soniox helpers — focused on the
pure functions and validation paths that the existing test_soniox.py
doesn't exercise."""

from __future__ import annotations

import pytest

from app.core import soniox
from app.core.soniox import (
    _build_segments_from_tokens,
    _language_hints,
    _require_api_key,
)


# ---------------------------------------------------------------------------
# _require_api_key
# ---------------------------------------------------------------------------


def test_require_api_key_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        soniox, "get_settings",
        lambda: SimpleNamespace(soniox_api_key=""),
    )
    # Function raises ValueError when key is missing.
    with pytest.raises(ValueError, match="SONIOX_API_KEY"):
        _require_api_key()


def test_require_api_key_returns_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        soniox, "get_settings",
        lambda: SimpleNamespace(soniox_api_key="sk-1234"),
    )
    assert _require_api_key() == "sk-1234"


# ---------------------------------------------------------------------------
# _language_hints
# ---------------------------------------------------------------------------


def test_language_hints_empty_returns_empty_list() -> None:
    assert _language_hints("") == []
    assert _language_hints("   ") == []


def test_language_hints_auto_returns_empty() -> None:
    assert _language_hints("auto") == []
    assert _language_hints("Auto") == []  # case-insensitive


def test_language_hints_multi_returns_empty() -> None:
    assert _language_hints("multi") == []
    assert _language_hints("MULTI") == []


def test_language_hints_returns_lowercased_language() -> None:
    assert _language_hints("EN") == ["en"]
    assert _language_hints("  Ru  ") == ["ru"]
    assert _language_hints("DE") == ["de"]


def test_language_hints_handles_none_input() -> None:
    # The "(language or '')" guard catches None.
    assert _language_hints(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _build_segments_from_tokens
# ---------------------------------------------------------------------------


def test_build_segments_raises_on_non_dict_token() -> None:
    with pytest.raises(RuntimeError, match="not an object"):
        _build_segments_from_tokens(["not-a-dict"])  # type: ignore[list-item]


def test_build_segments_skips_tokens_without_text() -> None:
    tokens = [{"text": "", "start_ms": 0, "end_ms": 100, "speaker": 1}]
    result = _build_segments_from_tokens(tokens)
    assert result == []


def test_build_segments_skips_translation_only_tokens() -> None:
    tokens = [
        {"text": "hi", "start_ms": 0, "end_ms": 100, "speaker": 1, "translation_status": "translation"},
    ]
    result = _build_segments_from_tokens(tokens)
    assert result == []


def test_build_segments_groups_by_speaker() -> None:
    tokens = [
        {"text": "Hello", "start_ms": 0, "end_ms": 100, "speaker": 1, "confidence": 0.9},
        {"text": " world", "start_ms": 100, "end_ms": 200, "speaker": 1, "confidence": 0.9},
        {"text": "Hi", "start_ms": 200, "end_ms": 300, "speaker": 2, "confidence": 0.85},
        {"text": " there", "start_ms": 300, "end_ms": 400, "speaker": 2, "confidence": 0.85},
    ]
    result = _build_segments_from_tokens(tokens)
    assert len(result) == 2
    assert result[0].speaker == "Speaker 1"
    assert "Hello" in result[0].text and "world" in result[0].text
    assert result[1].speaker == "Speaker 2"
    assert "Hi" in result[1].text and "there" in result[1].text


def test_build_segments_handles_missing_speaker() -> None:
    tokens = [
        {"text": "alone", "start_ms": 0, "end_ms": 50, "confidence": 0.8},
    ]
    result = _build_segments_from_tokens(tokens)
    assert len(result) == 1
    assert result[0].speaker is None


def test_build_segments_handles_missing_confidence() -> None:
    """Missing 'confidence' should default to 0.0, not crash."""
    tokens = [
        {"text": "x", "start_ms": 0, "end_ms": 10, "speaker": 1},
    ]
    result = _build_segments_from_tokens(tokens)
    assert len(result) == 1


def test_build_segments_handles_null_confidence() -> None:
    """confidence=None should not raise — `or 0.0` falls back."""
    tokens = [
        {"text": "x", "start_ms": 0, "end_ms": 10, "speaker": 1, "confidence": None},
    ]
    result = _build_segments_from_tokens(tokens)
    assert len(result) == 1
