"""Tests for Deepgram pre-recorded (batch) file transcription."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.deepgram import (
    build_batch_url,
    sanitize_deepgram_replacements,
    transcribe_audio_file,
)
from app.core.transcript_utils import TranscriptResult


def test_build_batch_url_includes_diarization_v2_and_formatting() -> None:
    url = build_batch_url(language="multi", multichannel=False)

    assert url.startswith("https://api.deepgram.com/v1/listen?")
    assert "model=nova-3" in url
    assert "diarize_model=latest" in url
    assert "smart_format=true" in url
    assert "punctuate=true" in url
    assert "paragraphs=true" in url
    assert "utterances=true" in url
    assert "language=multi" in url
    # diarize_model=latest selects the v2 batch diarizer and must NOT be paired
    # with diarize=true (Deepgram rejects that with HTTP 400).
    assert "diarize=true" not in url


def test_build_batch_url_enables_numerals_for_russian_but_not_japanese() -> None:
    russian = build_batch_url(language="ru", multichannel=False)
    japanese = build_batch_url(language="ja", multichannel=False)

    assert "language=ru" in russian
    assert "numerals=true" in russian
    assert "numerals=true" not in japanese


def test_build_batch_url_uses_multichannel_instead_of_diarization() -> None:
    url = build_batch_url(language="en", multichannel=True)

    assert "multichannel=true" in url
    assert "diarize_model=latest" not in url


def test_build_batch_url_sets_raw_pcm_encoding() -> None:
    url = build_batch_url(language="en", multichannel=False, raw_pcm=True)

    assert "encoding=linear16" in url
    assert "sample_rate=16000" in url
    assert "channels=1" in url


def test_build_batch_url_raw_pcm_multichannel_uses_actual_channel_count() -> None:
    url = build_batch_url(language="en", multichannel=True, raw_pcm=True, channels=2)

    assert "encoding=linear16" in url
    assert "channels=2" in url
    assert "multichannel=true" in url
    assert "diarize_model=latest" not in url


def test_build_batch_url_repeats_sanitized_keyterms() -> None:
    url = build_batch_url(
        language="multi",
        multichannel=False,
        keyterms=[" WaiComputer ", "WaiComputer", ""],
    )

    assert url.count("keyterm=") == 1
    assert "keyterm=WaiComputer" in url


def test_sanitize_deepgram_replacements_lowercases_find_and_drops_noops() -> None:
    pairs = sanitize_deepgram_replacements(
        [
            ("  WaiCompyuter ", "  WaiComputer "),  # trimmed; find lowercased
            ("kubernetes", "kubernetes"),  # find == replace → dropped
            ("Foo", "foo"),  # find == replace case-insensitively → dropped
            ("   ", "something"),  # empty find → dropped
            ("WAICOMPYUTER", "Other"),  # duplicate find (after lowercasing) → dropped
        ]
    )

    assert pairs == [("waicompyuter", "WaiComputer")]


def test_sanitize_deepgram_replacements_caps_at_200() -> None:
    many = [(f"find{index:04d}", f"Replace{index:04d}") for index in range(250)]

    pairs = sanitize_deepgram_replacements(many)

    assert len(pairs) == 200
    assert pairs[0] == ("find0000", "Replace0000")


def test_build_batch_url_includes_replace_pairs() -> None:
    url = build_batch_url(
        language="multi",
        multichannel=False,
        replacements=[("Bolnichny", "больничный"), ("Wai", "WaiComputer")],
    )

    # Each sanitized pair becomes a repeated replace=find:replace param
    # (colon URL-encoded to %3A; find is lowercased).
    assert url.count("replace=") == 2
    assert "replace=wai%3AWaiComputer" in url
    assert "replace=bolnichny%3A" in url


@pytest.mark.asyncio
async def test_transcribe_audio_file_parses_utterances_into_segments() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {
                        "start": 0.0,
                        "end": 1.2,
                        "confidence": 0.98,
                        "channel": 0,
                        "speaker": 0,
                        "transcript": "Hello there.",
                    },
                    {
                        "start": 1.3,
                        "end": 2.5,
                        "confidence": 0.91,
                        "channel": 0,
                        "speaker": 1,
                        "transcript": "Hi, how are you?",
                    },
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(
            b"wav-data", language="multi", content_type="audio/wav", channels=1
        )

    assert results == [
        TranscriptResult(
            text="Hello there.",
            speaker="speaker_0",
            is_final=True,
            start_ms=0,
            end_ms=1200,
            confidence=0.98,
        ),
        TranscriptResult(
            text="Hi, how are you?",
            speaker="speaker_1",
            is_final=True,
            start_ms=1300,
            end_ms=2500,
            confidence=0.91,
        ),
    ]
    sent_url = post.await_args.args[0]
    assert "diarize_model=latest" in sent_url
    assert post.await_args.kwargs["headers"]["Authorization"] == "Token deepgram-test-key"
    assert post.await_args.kwargs["headers"]["Content-Type"] == "audio/wav"
    assert post.await_args.kwargs["content"] == b"wav-data"


@pytest.mark.asyncio
async def test_transcribe_audio_file_detects_multichannel_wav() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {
                        "start": 0.0,
                        "end": 0.5,
                        "confidence": 0.9,
                        "channel": 0,
                        "transcript": "left channel",
                    }
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("app.core.deepgram.detect_wav_channels", return_value=2),
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(b"stereo-wav", content_type="audio/wav")

    assert results[0].speaker == "Channel 1"
    sent_url = post.await_args.args[0]
    assert "multichannel=true" in sent_url
    assert "diarize_model=latest" not in sent_url


@pytest.mark.asyncio
async def test_transcribe_audio_file_accepts_list_channel_index() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {
                        "start": 0.0,
                        "end": 0.5,
                        "confidence": 0.9,
                        "channel": [0, 1],
                        "transcript": "single channel list shape",
                    }
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(b"m4a", content_type="audio/mp4", channels=1)

    assert results[0].speaker == "Channel 1"


@pytest.mark.asyncio
async def test_transcribe_audio_file_normalizes_m4a_content_type() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {"start": 0.0, "end": 0.4, "confidence": 0.9, "speaker": 0, "transcript": "hi"}
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        await transcribe_audio_file(b"m4a-bytes", content_type="audio/x-m4a", channels=1)

    # audio/x-m4a (a web-upload alias) must be canonicalized to audio/mp4.
    assert post.await_args.kwargs["headers"]["Content-Type"] == "audio/mp4"


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_when_results_not_object() -> None:
    response = httpx.Response(
        200,
        json={"results": "not-a-dict"},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        with pytest.raises(RuntimeError, match="missing results object"):
            await transcribe_audio_file(b"wav", content_type="audio/wav", channels=1)


@pytest.mark.asyncio
async def test_transcribe_audio_file_speaker_none_without_speaker_or_channel() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {"start": 0.0, "end": 0.5, "confidence": 0.8, "transcript": "no speaker info"}
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(b"wav", content_type="audio/wav", channels=1)

    assert results[0].speaker is None


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_when_utterances_missing() -> None:
    response = httpx.Response(
        200,
        json={"results": {}},
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        with pytest.raises(RuntimeError, match="missing utterances"):
            await transcribe_audio_file(b"wav", content_type="audio/wav", channels=1)


@pytest.mark.asyncio
async def test_transcribe_audio_file_skips_empty_utterance_transcript() -> None:
    response = httpx.Response(
        200,
        json={
            "results": {
                "utterances": [
                    {
                        "start": 0.0,
                        "end": 0.1,
                        "confidence": 0.0,
                        "speaker": 0,
                        "transcript": "   ",
                    },
                    {
                        "start": 0.2,
                        "end": 0.5,
                        "confidence": 0.9,
                        "speaker": 0,
                        "transcript": "kept",
                    },
                ]
            }
        },
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        results = await transcribe_audio_file(b"wav", content_type="audio/wav", channels=1)

    assert [result.text for result in results] == ["kept"]


@pytest.mark.asyncio
async def test_transcribe_audio_file_requires_api_key() -> None:
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await transcribe_audio_file(b"wav", content_type="audio/wav", channels=1)
