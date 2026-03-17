"""Integration tests for multichannel audio -> backend transcript pipeline.

Tests the full flow: WAV channel detection -> Deepgram REST API call ->
multichannel result parsing -> TranscriptResult / Segment creation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.deepgram as deepgram_module
from app.core.deepgram import TranscriptResult, transcribe_audio_file


def _make_stereo_wav(extra_bytes: int = 100) -> bytes:
    """Build a minimal 2-channel WAV header followed by ``extra_bytes`` of silence."""
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = (2).to_bytes(2, "little")
    return bytes(header) + b"\x00" * extra_bytes


def _make_mono_wav(extra_bytes: int = 100) -> bytes:
    """Build a minimal 1-channel WAV header followed by ``extra_bytes`` of silence."""
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = (1).to_bytes(2, "little")
    return bytes(header) + b"\x00" * extra_bytes


def _deepgram_multichannel_response(
    ch0_paragraphs: list[dict],
    ch1_paragraphs: list[dict],
    ch0_confidence: float = 0.95,
    ch1_confidence: float = 0.92,
) -> dict:
    """Build a realistic Deepgram multichannel REST API response with paragraph data."""
    return {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "confidence": ch0_confidence,
                            "paragraphs": {"paragraphs": ch0_paragraphs},
                        }
                    ]
                },
                {
                    "alternatives": [
                        {
                            "confidence": ch1_confidence,
                            "paragraphs": {"paragraphs": ch1_paragraphs},
                        }
                    ]
                },
            ]
        }
    }


def _mock_httpx_client(response_data: dict) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns the given JSON response."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.fixture(autouse=True)
def mock_deepgram_settings():
    """Ensure tests have a fake Deepgram API key so we never hit the real API."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", "dg-test-key-mc"):
        yield


# ---------------------------------------------------------------------------
# 1. WAV detection -> multichannel API params
# ---------------------------------------------------------------------------
class TestWavDetectionToMultichannelParams:
    async def test_stereo_wav_triggers_multichannel_params(self):
        """A 2-channel WAV file causes multichannel=true and channels=2 in the API call."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [{"text": "Hello", "start": 0.0, "end": 0.5}],
            }],
            ch1_paragraphs=[{
                "sentences": [{"text": "Hi", "start": 0.1, "end": 0.4}],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            await transcribe_audio_file(audio, content_type="audio/wav")

        call_kwargs = mock_client.post.call_args
        params = call_kwargs.kwargs["params"]
        assert params["multichannel"] == "true"
        assert params["channels"] == "2"

    async def test_mono_wav_does_not_trigger_multichannel(self):
        """A 1-channel WAV file does NOT send multichannel params."""
        audio = _make_mono_wav()
        response = {"results": {"utterances": []}}
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            await transcribe_audio_file(audio, content_type="audio/wav")

        call_kwargs = mock_client.post.call_args
        params = call_kwargs.kwargs["params"]
        assert "multichannel" not in params
        assert "channels" not in params


# ---------------------------------------------------------------------------
# 2. Speaker assignment: ch0 -> "You", ch1 -> "Speaker 1"
# ---------------------------------------------------------------------------
class TestMultichannelSpeakerAssignment:
    async def test_channel_0_gets_speaker_you(self):
        """Channel 0 (mic) segments are labeled 'You'."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "I said something", "start": 0.0, "end": 1.0},
                    {"text": "And something else", "start": 1.5, "end": 2.5},
                ],
            }],
            ch1_paragraphs=[],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert len(results) == 2
        assert all(r.speaker == "You" for r in results)

    async def test_channel_1_gets_speaker_1(self):
        """Channel 1 (system audio) segments are labeled 'Speaker 1'."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "Remote person talking", "start": 0.5, "end": 2.0},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert len(results) == 1
        assert results[0].speaker == "Speaker 1"
        assert results[0].text == "Remote person talking"

    async def test_both_channels_get_correct_speakers(self):
        """Mixed results from both channels get the correct speaker labels."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "My question", "start": 0.0, "end": 1.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "Their answer", "start": 1.2, "end": 2.5},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        speakers = {r.speaker for r in results}
        assert speakers == {"You", "Speaker 1"}

        you_results = [r for r in results if r.speaker == "You"]
        remote_results = [r for r in results if r.speaker == "Speaker 1"]
        assert you_results[0].text == "My question"
        assert remote_results[0].text == "Their answer"


# ---------------------------------------------------------------------------
# 3. Empty sentence filtering
# ---------------------------------------------------------------------------
class TestEmptySentenceFiltering:
    async def test_empty_sentences_are_excluded(self):
        """Sentences with empty or whitespace-only text are filtered out."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "Real sentence", "start": 0.0, "end": 1.0},
                    {"text": "", "start": 1.0, "end": 1.5},
                    {"text": "   ", "start": 1.5, "end": 2.0},
                    {"text": "Another real one", "start": 2.0, "end": 3.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "", "start": 0.5, "end": 0.8},
                    {"text": "Valid remote speech", "start": 1.0, "end": 2.0},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        texts = [r.text for r in results]
        assert "" not in texts
        assert "   " not in texts
        assert len(results) == 3
        assert "Real sentence" in texts
        assert "Another real one" in texts
        assert "Valid remote speech" in texts

    async def test_all_empty_sentences_returns_empty_list(self):
        """When every sentence is empty, transcription returns an empty list."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "", "start": 0.0, "end": 0.5},
                    {"text": "  ", "start": 0.5, "end": 1.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "", "start": 0.2, "end": 0.7},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert results == []


# ---------------------------------------------------------------------------
# 4. Chronological sorting
# ---------------------------------------------------------------------------
class TestChronologicalSorting:
    async def test_results_sorted_by_start_ms(self):
        """Results from both channels are merged and sorted by start_ms."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "A (ch0, 2s)", "start": 2.0, "end": 3.0},
                    {"text": "B (ch0, 5s)", "start": 5.0, "end": 6.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "C (ch1, 0s)", "start": 0.0, "end": 1.0},
                    {"text": "D (ch1, 3.5s)", "start": 3.5, "end": 4.5},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert len(results) == 4
        # Expected order: C(0ms), A(2000ms), D(3500ms), B(5000ms)
        assert results[0].text == "C (ch1, 0s)"
        assert results[0].start_ms == 0
        assert results[0].speaker == "Speaker 1"

        assert results[1].text == "A (ch0, 2s)"
        assert results[1].start_ms == 2000
        assert results[1].speaker == "You"

        assert results[2].text == "D (ch1, 3.5s)"
        assert results[2].start_ms == 3500
        assert results[2].speaker == "Speaker 1"

        assert results[3].text == "B (ch0, 5s)"
        assert results[3].start_ms == 5000
        assert results[3].speaker == "You"

    async def test_interleaved_conversation_order(self):
        """A natural back-and-forth conversation is correctly chronologically interleaved."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "Hey, how's the project going?", "start": 0.0, "end": 1.5},
                    {"text": "That sounds great.", "start": 4.0, "end": 5.0},
                    {"text": "Let's ship it.", "start": 8.0, "end": 9.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "It's going well, almost done.", "start": 2.0, "end": 3.5},
                    {"text": "Should we deploy today?", "start": 5.5, "end": 7.0},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        # Verify conversation flows naturally
        assert len(results) == 5
        expected_order = [
            ("You", "Hey, how's the project going?"),
            ("Speaker 1", "It's going well, almost done."),
            ("You", "That sounds great."),
            ("Speaker 1", "Should we deploy today?"),
            ("You", "Let's ship it."),
        ]
        for result, (expected_speaker, expected_text) in zip(results, expected_order):
            assert result.speaker == expected_speaker, (
                f"Expected {expected_speaker} for '{expected_text}', got {result.speaker}"
            )
            assert result.text == expected_text


# ---------------------------------------------------------------------------
# 5. Full pipeline: WAV detection -> transcription -> segment-like creation
# ---------------------------------------------------------------------------
class TestFullPipelineSegmentCreation:
    async def test_full_pipeline_produces_correct_segment_data(self):
        """End-to-end: 2-channel WAV -> Deepgram API -> TranscriptResults with all fields."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "Tell me about the roadmap.", "start": 0.0, "end": 2.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "We have three milestones planned.", "start": 2.5, "end": 5.0},
                    {"text": "First one ships next week.", "start": 5.5, "end": 7.0},
                ],
            }],
            ch0_confidence=0.97,
            ch1_confidence=0.91,
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert len(results) == 3

        # Verify WAV detection worked (2 channels detected -> multichannel mode)
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["params"]["multichannel"] == "true"

        # Verify each result has all required fields for Segment creation
        for r in results:
            assert isinstance(r, TranscriptResult)
            assert isinstance(r.text, str) and r.text.strip()
            assert r.speaker in ("You", "Speaker 1")
            assert r.is_final is True
            assert isinstance(r.start_ms, int) and r.start_ms >= 0
            assert isinstance(r.end_ms, int) and r.end_ms > 0
            assert isinstance(r.confidence, float) and r.confidence > 0

        # Verify chronological order
        for i in range(len(results) - 1):
            assert results[i].start_ms <= results[i + 1].start_ms

        # Verify specific values
        assert results[0].speaker == "You"
        assert results[0].text == "Tell me about the roadmap."
        assert results[0].start_ms == 0
        assert results[0].end_ms == 2000
        assert results[0].confidence == 0.97

        assert results[1].speaker == "Speaker 1"
        assert results[1].text == "We have three milestones planned."
        assert results[1].start_ms == 2500
        assert results[1].end_ms == 5000
        assert results[1].confidence == 0.91

        assert results[2].speaker == "Speaker 1"
        assert results[2].text == "First one ships next week."
        assert results[2].start_ms == 5500
        assert results[2].end_ms == 7000

    async def test_pipeline_with_paragraph_fallback_to_full_transcript(self):
        """When paragraphs are missing, the pipeline falls back to the full transcript."""
        audio = _make_stereo_wav()
        # No paragraphs — only raw transcript + words
        response = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "Mic audio here",
                                "confidence": 0.88,
                                "words": [
                                    {"word": "Mic", "start": 0.0, "end": 0.3},
                                    {"word": "audio", "start": 0.3, "end": 0.6},
                                    {"word": "here", "start": 0.6, "end": 0.9},
                                ],
                            }
                        ]
                    },
                    {
                        "alternatives": [
                            {
                                "transcript": "System audio here",
                                "confidence": 0.85,
                                "words": [
                                    {"word": "System", "start": 0.1, "end": 0.4},
                                    {"word": "audio", "start": 0.4, "end": 0.7},
                                    {"word": "here", "start": 0.7, "end": 1.0},
                                ],
                            }
                        ]
                    },
                ]
            }
        }
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        assert len(results) == 2
        # Sorted chronologically: ch0 at 0ms, ch1 at 100ms
        assert results[0].speaker == "You"
        assert results[0].text == "Mic audio here"
        assert results[0].start_ms == 0
        assert results[0].end_ms == 900

        assert results[1].speaker == "Speaker 1"
        assert results[1].text == "System audio here"
        assert results[1].start_ms == 100
        assert results[1].end_ms == 1000

    async def test_duration_calculation_from_results(self):
        """The maximum end_ms across all results can compute recording duration."""
        audio = _make_stereo_wav()
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [
                    {"text": "Start of conversation", "start": 0.0, "end": 2.0},
                ],
            }],
            ch1_paragraphs=[{
                "sentences": [
                    {"text": "End of conversation", "start": 10.0, "end": 15.0},
                ],
            }],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio, content_type="audio/wav")

        # Replicate what the recording upload handler does
        max_end_ms = max(r.end_ms for r in results)
        duration_seconds = max_end_ms // 1000
        assert duration_seconds == 15

        # Joined transcript text (as used for title generation)
        transcript_text = " ".join(r.text for r in results if r.text.strip())
        assert transcript_text == "Start of conversation End of conversation"


# ---------------------------------------------------------------------------
# 6. Explicit channels parameter
# ---------------------------------------------------------------------------
class TestExplicitChannelsParameter:
    async def test_explicit_channels_overrides_wav_detection(self):
        """Passing channels=2 explicitly works even for non-WAV content types."""
        audio = b"not-a-wav-file-but-has-two-channels"
        response = _deepgram_multichannel_response(
            ch0_paragraphs=[{
                "sentences": [{"text": "Forced multichannel", "start": 0.0, "end": 1.0}],
            }],
            ch1_paragraphs=[],
        )
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(
                audio, content_type="audio/webm", channels=2
            )

        assert len(results) == 1
        assert results[0].speaker == "You"

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["params"]["multichannel"] == "true"
        assert call_kwargs.kwargs["params"]["channels"] == "2"

    async def test_channels_1_does_not_trigger_multichannel(self):
        """Explicitly passing channels=1 keeps single-channel (utterance) mode."""
        audio = _make_stereo_wav()  # header says 2 channels but we override with 1
        response = {
            "results": {
                "utterances": [
                    {
                        "transcript": "Single channel mode",
                        "speaker": 0,
                        "start": 0.0,
                        "end": 1.5,
                        "confidence": 0.93,
                    },
                ]
            }
        }
        mock_client = _mock_httpx_client(response)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(
                audio, content_type="audio/wav", channels=1
            )

        assert len(results) == 1
        assert results[0].text == "Single channel mode"
        assert results[0].speaker == "Speaker 0"

        call_kwargs = mock_client.post.call_args
        assert "multichannel" not in call_kwargs.kwargs["params"]
