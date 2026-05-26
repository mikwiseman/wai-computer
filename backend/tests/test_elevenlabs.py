"""Tests for ElevenLabs helpers."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.elevenlabs import (
    ElevenLabsAgentSummary,
    ElevenLabsSignedUrl,
    _confidence_from_words,
    _result_from_transcript,
    _results_from_transcript,
    _stt_upload_filename,
    get_signed_url,
    list_agents,
    transcribe_audio_file,
)
from app.core.transcript_utils import TranscriptResult


def test_confidence_from_words_uses_average_logprob():
    confidence = _confidence_from_words(
        [
            {"logprob": -1.0},
            {"logprob": -2.0},
            {"logprob": -3.0},
        ]
    )
    assert 0.0 < confidence < 1.0


def test_confidence_from_words_returns_zero_without_logprobs():
    assert _confidence_from_words([{"word": "hello"}]) == 0.0


def test_result_from_transcript_builds_segment():
    result = _result_from_transcript(
        {
            "text": "hello world",
            "words": [
                {"start": 0.1, "end": 0.3, "speaker_id": "Speaker A", "logprob": -0.5},
                {"start": 0.31, "end": 0.6, "speaker_id": "Speaker A", "logprob": -0.3},
            ],
        }
    )

    assert isinstance(result, TranscriptResult)
    assert result.text == "hello world"
    assert result.speaker == "Speaker A"
    assert result.start_ms == 100
    assert result.end_ms == 600


def test_result_from_transcript_returns_none_for_empty_text():
    assert _result_from_transcript({"text": "   "}) is None


def test_results_from_transcript_skips_empty_word_groups():
    results = _results_from_transcript(
        {
            "text": "hello",
            "words": [
                {"text": "", "speaker_id": "Speaker 1", "start": 0.0, "end": 0.1},
                {"text": "hello", "speaker_id": "Speaker 2", "start": 0.2, "end": 0.4},
            ],
        }
    )

    assert len(results) == 1
    assert results[0].text == "hello"
    assert results[0].speaker == "Speaker 2"


def test_stt_upload_filename_rejects_unsupported_content_type():
    with pytest.raises(ValueError, match="Unsupported ElevenLabs STT content type"):
        _stt_upload_filename("application/octet-stream")


@pytest.mark.asyncio
async def test_get_signed_url_returns_expected_payload():
    response = httpx.Response(
        200,
        json={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent-1"},
        request=httpx.Request(
            "GET",
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        ),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        signed_url = await get_signed_url(agent_id="agent-1", environment="production")

    assert signed_url == ElevenLabsSignedUrl(
        signed_url="wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent-1",
        agent_id="agent-1",
    )


@pytest.mark.asyncio
async def test_get_signed_url_rejects_missing_payload_value():
    response = httpx.Response(
        200,
        json={},
        request=httpx.Request(
            "GET",
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        ),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        with pytest.raises(RuntimeError, match="invalid signed_url"):
            await get_signed_url(agent_id="agent-1", branch_id="branch-1")


@pytest.mark.asyncio
async def test_list_agents_returns_owned_agents():
    response = httpx.Response(
        200,
        json={
            "agents": [
                {"agent_id": "agent-1", "name": "Wai Primary"},
                {"agent_id": "agent-2", "name": "Wai Backup"},
            ]
        },
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        agents = await list_agents(page_size=2)

    assert agents == [
        ElevenLabsAgentSummary(agent_id="agent-1", name="Wai Primary"),
        ElevenLabsAgentSummary(agent_id="agent-2", name="Wai Backup"),
    ]


@pytest.mark.asyncio
async def test_list_agents_skips_invalid_entries():
    response = httpx.Response(
        200,
        json={
            "agents": [
                "bad-entry",
                {"name": "Missing id"},
                {"agent_id": "agent-3", "name": "Wai Valid"},
            ]
        },
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        agents = await list_agents()

    assert agents == [ElevenLabsAgentSummary(agent_id="agent-3", name="Wai Valid")]


@pytest.mark.asyncio
async def test_list_agents_rejects_invalid_payload():
    response = httpx.Response(
        200,
        json={},
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        with pytest.raises(RuntimeError, match="invalid agents payload"):
            await list_agents()


@pytest.mark.asyncio
async def test_transcribe_audio_file_handles_multi_transcript_payload():
    response = httpx.Response(
        200,
        json={
            "transcripts": [
                {
                    "text": "hello",
                    "words": [
                        {"start": 0.0, "end": 0.5, "speaker_id": "Speaker 1", "logprob": -0.1}
                    ],
                },
                {
                    "text": "world",
                    "words": [
                        {"start": 0.5, "end": 1.0, "speaker_id": "Speaker 2", "logprob": -0.2}
                    ],
                },
            ]
        },
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        results = await transcribe_audio_file(b"wav-data", content_type="audio/wav")

    assert [result.text for result in results] == ["hello", "world"]


@pytest.mark.asyncio
async def test_transcribe_audio_file_splits_diarized_word_speaker_turns():
    def word(
        text: str,
        start: float,
        end: float,
        speaker_id: str,
        logprob: float,
    ) -> dict:
        return {
            "text": text,
            "start": start,
            "end": end,
            "speaker_id": speaker_id,
            "logprob": logprob,
        }

    response = httpx.Response(
        200,
        json={
            "text": "Alice starts. Bob replies. Alice finishes.",
            "words": [
                word("Alice", 0.0, 0.2, "Speaker 1", -0.1),
                word("starts", 0.2, 0.5, "Speaker 1", -0.1),
                word(".", 0.5, 0.51, "Speaker 1", -0.1),
                word("Bob", 0.6, 0.8, "Speaker 2", -0.2),
                word("replies", 0.8, 1.1, "Speaker 2", -0.2),
                word(".", 1.1, 1.11, "Speaker 2", -0.2),
                word("Alice", 1.2, 1.4, "Speaker 1", -0.15),
                word("finishes", 1.4, 1.8, "Speaker 1", -0.15),
                word(".", 1.8, 1.81, "Speaker 1", -0.15),
            ],
        },
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = True
        results = await transcribe_audio_file(b"wav-data", content_type="audio/wav")

    assert [(result.speaker, result.text) for result in results] == [
        ("Speaker 1", "Alice starts."),
        ("Speaker 2", "Bob replies."),
        ("Speaker 1", "Alice finishes."),
    ]
    assert [(result.start_ms, result.end_ms) for result in results] == [
        (0, 510),
        (600, 1110),
        (1200, 1810),
    ]


@pytest.mark.asyncio
async def test_transcribe_audio_file_handles_single_payload_and_raw_audio():
    response = httpx.Response(
        200,
        json={"text": "hello raw"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = True
        results = await transcribe_audio_file(
            b"raw-data",
            content_type="audio/raw",
            channels=1,
            language="multi",
        )

    assert len(results) == 1
    assert results[0].text == "hello raw"
    assert post.await_args.kwargs["data"]["no_verbatim"] == "true"
    assert post.await_args.kwargs["data"]["file_format"] == "pcm_s16le_16"
    assert post.await_args.kwargs["files"]["file"][0] == "recording.raw"


@pytest.mark.asyncio
async def test_transcribe_audio_file_sends_filename_matching_content_type():
    response = httpx.Response(
        200,
        json={"text": "hello wav"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = True
        results = await transcribe_audio_file(b"wav-data", content_type="audio/wav")

    assert results[0].text == "hello wav"
    assert post.await_args.kwargs["files"]["file"] == (
        "recording.wav",
        b"wav-data",
        "audio/wav",
    )


@pytest.mark.asyncio
async def test_transcribe_audio_file_omits_auto_language_code():
    response = httpx.Response(
        200,
        json={"text": "hello auto"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = False
        results = await transcribe_audio_file(
            b"wav-data",
            content_type="audio/wav",
            language=" auto ",
        )

    assert results[0].text == "hello auto"
    assert "language_code" not in post.await_args.kwargs["data"]


@pytest.mark.asyncio
async def test_transcribe_audio_file_normalizes_region_language_code():
    response = httpx.Response(
        200,
        json={"text": "hello region"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    post = AsyncMock(return_value=response)

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=post),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = False
        results = await transcribe_audio_file(
            b"wav-data",
            content_type="audio/wav",
            language="ru-RU",
        )

    assert results[0].text == "hello region"
    assert post.await_args.kwargs["data"]["language_code"] == "ru"


@pytest.mark.asyncio
async def test_transcribe_audio_file_rejects_invalid_transcript_entries():
    response = httpx.Response(
        200,
        json={"transcripts": ["bad", {"text": ""}]},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=2),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        with pytest.raises(RuntimeError, match="invalid transcript entry"):
            await transcribe_audio_file(b"stereo-data", content_type="audio/wav")


@pytest.mark.asyncio
async def test_transcribe_audio_file_handles_unexpected_payload_type():
    response = httpx.Response(
        200,
        json=[],
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("app.core.elevenlabs.detect_wav_channels", return_value=1),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        with pytest.raises(RuntimeError, match="unexpected payload type"):
            await transcribe_audio_file(b"wav-data", content_type="audio/wav")


@pytest.mark.asyncio
async def test_transcribe_audio_file_requires_api_key():
    with patch("app.core.elevenlabs.get_settings") as mock_settings:
        mock_settings.return_value.elevenlabs_api_key = ""
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"

        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY not configured"):
            await transcribe_audio_file(b"wav-data")
