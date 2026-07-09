"""Tests for Deepgram speech-to-text helpers."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.deepgram import (
    _detected_language_from_deepgram,
    _file_content_chunks,
    _integer_index,
    _wav_header_bytes,
    _words_from_deepgram_utterance,
    build_realtime_websocket_url,
    normalize_deepgram_language,
    require_deepgram_api_key,
    sanitize_deepgram_keyterms,
    transcribe_audio_file,
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


def test_build_realtime_websocket_url_uses_faster_endpointing_for_dictation() -> None:
    dictation = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="dictation",
    )
    recording = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="recording",
    )

    assert "endpointing=10" in dictation
    assert "endpointing=300" in recording


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


def test_build_realtime_websocket_url_includes_replace_pairs() -> None:
    url = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="dictation",
        replacements=[("Bolnichny", "больничный"), ("Wai", "WaiComputer")],
    )

    assert url.count("replace=") == 2
    assert "replace=wai%3AWaiComputer" in url
    assert "replace=bolnichny%3A" in url


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
    assert "dictation=true" not in russian  # spoken-punctuation cmds: English only
    assert "punctuate=true" in russian  # punctuation: all dictation languages
    assert "numerals=true" in russian


def test_build_realtime_websocket_url_dictation_uses_numerals_without_smart_format() -> None:
    """Dictation must render every spoken number as a digit (десять -> 10).

    Deepgram's numerals feature only converts small numbers when smart_format is
    OFF; smart_format's readability layer overrides it and leaves them as words
    ("десять"). Dictation therefore drops smart_format (numerals + punctuate),
    while recording keeps smart_format for readable meeting transcripts.
    """
    dictation = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="dictation",
    )
    recording = build_realtime_websocket_url(
        language="multi",
        channels=1,
        purpose="recording",
    )

    assert "numerals=true" in dictation
    assert "punctuate=true" in dictation
    assert "smart_format=true" not in dictation
    # Recording keeps smart_format (readability) and still gets numerals.
    assert "smart_format=true" in recording
    assert "numerals=true" in recording


def test_require_deepgram_api_key_returns_configured_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"

        assert require_deepgram_api_key() == "deepgram-test-key"


def test_require_deepgram_api_key_requires_configured_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""

        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            require_deepgram_api_key()


def test_integer_index_accepts_only_integer_values() -> None:
    assert _integer_index(True) is None
    assert _integer_index(3.0) == 3
    assert _integer_index(" 7 ") == 7
    assert _integer_index("x") is None
    assert _integer_index(2.5) is None


def test_words_from_deepgram_utterance_rejects_non_list_words() -> None:
    assert _words_from_deepgram_utterance({"words": "nope"}) == []


def test_words_from_deepgram_utterance_skips_invalid_words_and_bool_confidence() -> None:
    words = _words_from_deepgram_utterance(
        {
            "speaker": 0,
            "words": [
                "x",
                {"punctuated_word": "", "word": ""},
                {"word": "Привет", "start": 0.1, "end": 0.5, "confidence": True},
            ],
        }
    )

    assert len(words) == 1
    assert words[0].text == "Привет"
    assert words[0].confidence is None


def test_detected_language_from_deepgram_handles_missing_and_bool_confidence() -> None:
    assert _detected_language_from_deepgram({"channels": []}) == (None, None)
    assert _detected_language_from_deepgram(
        {"channels": [{"detected_language": "ru", "language_confidence": 0.9}]}
    ) == ("ru", 0.9)
    assert _detected_language_from_deepgram(
        {"channels": [{"detected_language": "ru", "language_confidence": True}]}
    ) == ("ru", None)


@pytest.mark.asyncio
async def test_file_content_chunks_streams_path_and_wav_header_reads_prefix(tmp_path) -> None:
    content = b"RIFF" + b"x" * 70_000
    path = tmp_path / "recording.wav"
    path.write_bytes(content)

    assert _wav_header_bytes(path) == content[: 64 * 1024]
    chunks = []
    async for chunk in _file_content_chunks(path):
        chunks.append(chunk)
    assert b"".join(chunks) == content


@pytest.mark.asyncio
async def test_transcribe_audio_file_clamps_path_wav_channels(tmp_path) -> None:
    header = bytearray(44)
    header[:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = (2).to_bytes(2, byteorder="little")
    path = tmp_path / "stereo.wav"
    path.write_bytes(bytes(header) + b"audio")
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {
                        "start": 0.0,
                        "end": 0.5,
                        "confidence": 0.9,
                        "speaker": 0,
                        "transcript": "clamped",
                    }
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
        patch("app.core.observability.capture_sentry_anomaly") as capture,
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(
            path,
            content_type="audio/wav",
            max_channels=1,
        )

    assert [segment.text for segment in results.segments] == ["clamped"]
    capture.assert_called_once()
    assert capture.call_args.args[0] == "recording.file_stt.channels_clamped"
