"""Tests for app/core/deepgram.py - Deepgram streaming and REST transcription."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.deepgram as deepgram_module
from app.core.deepgram import (
    DeepgramStreamingClient,
    TranscriptResult,
    detect_wav_channels,
    transcribe_audio_file,
)


@pytest.fixture(autouse=True)
def mock_deepgram_settings():
    """Patch settings on the already-imported module for each test."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", "dg-test-key-123"):
        yield


class TestBuildUrl:
    def test_constructs_correct_url_with_all_params(self):
        """_build_url() includes model, language, punctuate, diarize, and other params."""
        client = DeepgramStreamingClient(language="en", model="nova-3")
        url = client._build_url()

        assert "model=nova-3" in url
        assert "language=en" in url
        assert "punctuate=true" in url
        assert "diarize=true" in url
        assert "interim_results=true" in url
        assert "utterance_end_ms=1000" in url
        assert "vad_events=true" in url
        assert "encoding=linear16" in url
        assert "sample_rate=16000" in url

    def test_uses_nova_3_by_default(self):
        """The default model favors the current multilingual streaming model."""
        client = DeepgramStreamingClient(language="multi")
        url = client._build_url()

        assert "model=nova-3" in url
        assert "language=multi" in url

    def test_base_url_is_deepgram_ws(self):
        """_build_url() uses the correct Deepgram WebSocket base URL."""
        client = DeepgramStreamingClient()
        url = client._build_url()

        assert url.startswith("wss://api.deepgram.com/v1/listen?")

    def test_custom_model_and_language(self):
        """_build_url() respects custom model and language settings."""
        client = DeepgramStreamingClient(language="es", model="nova-3")
        url = client._build_url()

        assert "model=nova-3" in url
        assert "language=es" in url


class TestConnect:
    async def test_missing_api_key_raises_value_error(self):
        """connect() raises ValueError when DEEPGRAM_API_KEY is empty."""
        with patch.object(deepgram_module.settings, "deepgram_api_key", ""):
            client = DeepgramStreamingClient()
            with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
                await client.connect()

    async def test_calls_websockets_connect_with_correct_params(self):
        """connect() calls websockets.connect with the correct URL and auth headers."""
        mock_ws = AsyncMock()

        with patch("app.core.deepgram.websockets") as mock_websockets:
            mock_websockets.connect = AsyncMock(return_value=mock_ws)

            client = DeepgramStreamingClient(language="en", model="nova-3")
            result = await client.connect()

        assert result is True
        assert client._running is True
        assert client._ws is mock_ws

        mock_websockets.connect.assert_called_once()
        call_kwargs = mock_websockets.connect.call_args
        url_arg = call_kwargs.args[0]
        assert url_arg.startswith("wss://api.deepgram.com/v1/listen?")
        assert call_kwargs.kwargs["additional_headers"]["Authorization"] == "Token dg-test-key-123"


class TestSendAudio:
    async def test_forwards_bytes_to_websocket(self):
        """send_audio() sends data through the websocket when connected."""
        mock_ws = AsyncMock()
        client = DeepgramStreamingClient()
        client._ws = mock_ws
        client._running = True

        audio_data = b"\x00\x01\x02\x03"
        await client.send_audio(audio_data)

        mock_ws.send.assert_called_once_with(audio_data)

    async def test_raises_when_not_connected(self):
        """send_audio() fails fast when the stream is no longer active."""
        client = DeepgramStreamingClient()
        client._ws = None
        client._running = False

        with pytest.raises(RuntimeError, match="not active"):
            await client.send_audio(b"audio-data")


class TestReceiveTranscripts:
    async def test_yields_nothing_when_not_connected(self):
        """receive_transcripts() yields nothing when websocket is None."""
        client = DeepgramStreamingClient()
        client._ws = None

        results = []
        async for result in client.receive_transcripts():
            results.append(result)

        assert results == []

    async def test_parses_deepgram_results_format(self):
        """receive_transcripts() parses Deepgram Results with words, speaker, timing."""
        deepgram_message = json.dumps({
            "type": "Results",
            "is_final": True,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "Hello, how are you?",
                        "confidence": 0.95,
                        "words": [
                            {"word": "Hello", "speaker": 1, "start": 0.5, "end": 0.8},
                            {"word": "how", "speaker": 1, "start": 0.9, "end": 1.0},
                            {"word": "are", "speaker": 1, "start": 1.0, "end": 1.1},
                            {"word": "you", "speaker": 1, "start": 1.1, "end": 1.3},
                        ],
                    }
                ]
            },
        })

        # Create an async iterator that yields one message
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([deepgram_message]).__iter__())

        # We need a proper async iterator
        async def async_messages():
            yield deepgram_message

        mock_ws.__aiter__ = lambda self: async_messages()

        client = DeepgramStreamingClient()
        client._ws = mock_ws
        client._running = True

        # Manually implement the async iteration since mock_ws needs to work as async for
        results = []

        # Patch the websocket to be an async iterable
        class AsyncWSIterator:
            def __init__(self, messages):
                self._messages = messages
                self._index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._index >= len(self._messages):
                    raise StopAsyncIteration
                msg = self._messages[self._index]
                self._index += 1
                return msg

        client._ws = AsyncWSIterator([deepgram_message])
        # Also need close() for the client
        client._ws.close = AsyncMock()

        async for result in client.receive_transcripts():
            results.append(result)

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, TranscriptResult)
        assert result.text == "Hello, how are you?"
        assert result.speaker == "Speaker 1"
        assert result.is_final is True
        assert result.start_ms == 500  # 0.5 * 1000
        assert result.end_ms == 1300  # 1.3 * 1000
        assert result.confidence == 0.95

    async def test_skips_non_results_messages(self):
        """receive_transcripts() ignores messages that are not type 'Results'."""
        metadata_msg = json.dumps({"type": "Metadata", "request_id": "abc123"})
        results_msg = json.dumps({
            "type": "Results",
            "is_final": True,
            "channel": {
                "alternatives": [
                    {
                        "transcript": "Test",
                        "confidence": 0.9,
                        "words": [{"word": "Test", "speaker": 0, "start": 0.0, "end": 0.5}],
                    }
                ]
            },
        })

        class AsyncWSIterator:
            def __init__(self, messages):
                self._messages = messages
                self._index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._index >= len(self._messages):
                    raise StopAsyncIteration
                msg = self._messages[self._index]
                self._index += 1
                return msg

        client = DeepgramStreamingClient()
        client._ws = AsyncWSIterator([metadata_msg, results_msg])
        client._ws.close = AsyncMock()
        client._running = True

        results = []
        async for result in client.receive_transcripts():
            results.append(result)

        assert len(results) == 1
        assert results[0].text == "Test"


class TestClose:
    async def test_closes_websocket_and_resets_state(self):
        """close() closes the websocket and resets _ws and _running."""
        mock_ws = AsyncMock()
        client = DeepgramStreamingClient()
        client._ws = mock_ws
        client._running = True

        await client.close()

        assert client._running is False
        assert client._ws is None
        mock_ws.close.assert_called_once()

    async def test_close_when_not_connected(self):
        """close() handles the case where websocket is already None."""
        client = DeepgramStreamingClient()
        client._ws = None
        client._running = False

        # Should not raise
        await client.close()
        assert client._running is False


class TestDetectWavChannels:
    def test_mono_wav(self):
        """detect_wav_channels() returns 1 for mono WAV."""
        # Minimal WAV header: RIFF...WAVE...fmt with 1 channel at byte 22
        header = bytearray(44)
        header[0:4] = b"RIFF"
        header[8:12] = b"WAVE"
        header[22:24] = (1).to_bytes(2, "little")
        assert detect_wav_channels(bytes(header)) == 1

    def test_stereo_wav(self):
        """detect_wav_channels() returns 2 for stereo WAV."""
        header = bytearray(44)
        header[0:4] = b"RIFF"
        header[8:12] = b"WAVE"
        header[22:24] = (2).to_bytes(2, "little")
        assert detect_wav_channels(bytes(header)) == 2

    def test_not_wav(self):
        """detect_wav_channels() returns 1 for non-WAV data."""
        assert detect_wav_channels(b"not a wav file at all") == 1

    def test_too_short(self):
        """detect_wav_channels() returns 1 for data shorter than a WAV header."""
        assert detect_wav_channels(b"RIFF") == 1

    def test_empty(self):
        """detect_wav_channels() returns 1 for empty data."""
        assert detect_wav_channels(b"") == 1


class TestTranscribeAudioFile:
    async def test_missing_api_key_raises_value_error(self):
        """transcribe_audio_file() raises ValueError when API key is empty."""
        with patch.object(deepgram_module.settings, "deepgram_api_key", ""):
            with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
                await transcribe_audio_file(b"audio-data")

    async def test_makes_correct_rest_api_call(self):
        """transcribe_audio_file() makes correct POST to Deepgram REST API."""
        deepgram_response = {
            "results": {
                "utterances": [
                    {
                        "transcript": "Hello world",
                        "speaker": 0,
                        "start": 0.0,
                        "end": 1.5,
                        "confidence": 0.98,
                    },
                    {
                        "transcript": "How are you",
                        "speaker": 1,
                        "start": 2.0,
                        "end": 3.0,
                        "confidence": 0.95,
                    },
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = deepgram_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(
                b"fake-audio", language="en", model="nova-2"
            )

        assert len(results) == 2

        assert results[0].text == "Hello world"
        assert results[0].speaker == "Speaker 0"
        assert results[0].is_final is True
        assert results[0].start_ms == 0
        assert results[0].end_ms == 1500
        assert results[0].confidence == 0.98

        assert results[1].text == "How are you"
        assert results[1].speaker == "Speaker 1"
        assert results[1].start_ms == 2000
        assert results[1].end_ms == 3000

        # Verify the API was called correctly
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.args[0] == "https://api.deepgram.com/v1/listen"
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Token dg-test-key-123"
        assert call_kwargs.kwargs["headers"]["Content-Type"] == "audio/wav"
        assert call_kwargs.kwargs["content"] == b"fake-audio"
        assert call_kwargs.kwargs["params"]["model"] == "nova-2"
        assert call_kwargs.kwargs["params"]["language"] == "en"
        assert call_kwargs.kwargs["params"]["punctuate"] == "true"
        assert call_kwargs.kwargs["params"]["diarize"] == "true"
        assert call_kwargs.kwargs["timeout"] == 300.0

    async def test_multichannel_wav_auto_detected(self):
        """transcribe_audio_file() auto-detects 2-channel WAV and uses multichannel mode."""
        # Build minimal 2-channel WAV header
        wav_header = bytearray(44)
        wav_header[0:4] = b"RIFF"
        wav_header[8:12] = b"WAVE"
        wav_header[22:24] = (2).to_bytes(2, "little")  # 2 channels
        audio_data = bytes(wav_header) + b"\x00" * 100

        deepgram_response = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "Hello from mic",
                                "confidence": 0.95,
                                "words": [
                                    {"word": "Hello", "start": 0.0, "end": 0.5},
                                    {"word": "from", "start": 0.5, "end": 0.8},
                                    {"word": "mic", "start": 0.8, "end": 1.0},
                                ],
                            }
                        ]
                    },
                    {
                        "alternatives": [
                            {
                                "transcript": "Hi from system",
                                "confidence": 0.92,
                                "words": [
                                    {"word": "Hi", "start": 0.2, "end": 0.4},
                                    {"word": "from", "start": 0.4, "end": 0.6},
                                    {"word": "system", "start": 0.6, "end": 0.9},
                                ],
                            }
                        ]
                    },
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = deepgram_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(audio_data, content_type="audio/wav")

        assert len(results) == 2

        # Sorted by start_ms: ch1 "Hi" at 200ms comes after ch0 "Hello" at 0ms
        assert results[0].speaker == "You"
        assert results[0].text == "Hello from mic"
        assert results[0].start_ms == 0
        assert results[1].speaker == "Speaker 1"
        assert results[1].text == "Hi from system"
        assert results[1].start_ms == 200

        # Verify multichannel params were sent
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["params"]["multichannel"] == "true"
        assert call_kwargs.kwargs["params"]["channels"] == "2"

    async def test_returns_empty_list_when_no_utterances(self):
        """transcribe_audio_file() returns empty list when no utterances in response."""
        deepgram_response = {"results": {"utterances": []}}

        mock_response = MagicMock()
        mock_response.json.return_value = deepgram_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
            results = await transcribe_audio_file(b"silent-audio")

        assert results == []
