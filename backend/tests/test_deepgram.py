"""Tests for Deepgram speech-to-text helpers."""

from unittest.mock import patch

import pytest

from app.core.deepgram import (
    build_realtime_websocket_url,
    normalize_deepgram_language,
    require_deepgram_api_key,
    sanitize_deepgram_keyterms,
    validate_deepgram_language,
)


def test_normalize_deepgram_language_maps_auto_to_multi() -> None:
    assert normalize_deepgram_language(None) == "multi"
    assert normalize_deepgram_language("  ") == "multi"
    assert normalize_deepgram_language("AUTO") == "multi"
    assert normalize_deepgram_language("ru_RU") == "ru"
    assert normalize_deepgram_language("en_GB") == "en-gb"
    assert normalize_deepgram_language("es_MX") == "es"
    assert normalize_deepgram_language("zz-TEST") == "zz-test"


def test_validate_deepgram_language_accepts_supported_language() -> None:
    assert validate_deepgram_language("ru") == "ru"
    assert validate_deepgram_language("multi") == "multi"


def test_validate_deepgram_language_rejects_unsupported_language() -> None:
    with pytest.raises(ValueError, match="Unsupported Deepgram language"):
        validate_deepgram_language("zz-TEST")


def test_build_realtime_websocket_url_includes_live_best_practice_params() -> None:
    url = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="recording",
    )

    assert url.startswith("wss://api.deepgram.com/v1/listen?")
    assert "model=nova-3" in url
    assert "encoding=linear16" in url
    assert "sample_rate=16000" in url
    assert "language=multi" in url
    assert "interim_results=true" in url
    assert "smart_format=true" in url
    assert "utterance_end_ms=1000" in url
    assert "endpointing=300" in url
    assert "utterances=true" in url
    assert "diarize=true" in url


def test_build_realtime_websocket_url_omits_diarize_for_dictation() -> None:
    url = build_realtime_websocket_url(
        language="en-US",
        channels=1,
        purpose="dictation",
    )

    assert "diarize=true" not in url


def test_build_realtime_websocket_url_repeats_sanitized_keyterm_params() -> None:
    url = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="recording",
        keyterms=[" WaiComputer ", "больничный", "WaiComputer", ""],
    )

    assert url.count("keyterm=") == 2
    assert "keyterm=WaiComputer" in url
    assert (
        "keyterm=%D0%B1%D0%BE%D0%BB%D1%8C%D0%BD%D0%B8%D1%87%D0%BD%D1%8B%D0%B9"
        in url
    )


def test_sanitize_deepgram_keyterms_caps_token_budget() -> None:
    terms = [f"term{i}" for i in range(150)]

    sanitized = sanitize_deepgram_keyterms(terms)

    assert len(sanitized) == 100
    assert sanitized[0] == "term0"
    assert sanitized[-1] == "term99"


def test_build_realtime_websocket_url_limits_dictation_to_english() -> None:
    english = build_realtime_websocket_url(
        language="en-US",
        channels=1,
        purpose="dictation",
    )
    russian = build_realtime_websocket_url(
        language="ru",
        channels=1,
        purpose="dictation",
    )

    assert "dictation=true" in english
    assert "punctuate=true" in english
    assert "numerals=true" in english
    assert "dictation=true" not in russian
    assert "punctuate=true" not in russian
    assert "numerals=true" in russian


def test_build_realtime_websocket_url_keeps_numeric_entities_whole() -> None:
    """Multilingual dictation must not use aggressive endpointing.

    Deepgram's streaming smart_format/numerals only convert a number once the
    whole numeric phrase finalizes together. A 100ms endpointing used to split
    multilingual phrases across finals so only part converted. The multilingual
    path must share the same non-aggressive 300ms as single-language so numerals
    stay whole.
    """
    multi = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="dictation",
    )
    russian = build_realtime_websocket_url(
        language="ru",
        channels=1,
        purpose="dictation",
    )

    assert "endpointing=300" in multi
    assert "endpointing=100" not in multi
    assert "numerals=true" in multi
    # Multilingual and single-language finalize at the same cadence.
    assert "endpointing=300" in russian


def test_require_deepgram_api_key_returns_configured_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = "dg-key"

        assert require_deepgram_api_key() == "dg-key"


def test_require_deepgram_api_key_requires_configured_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""

        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            require_deepgram_api_key()
