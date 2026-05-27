"""Tests for OpenAI speech-to-text helpers."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.openai_transcription import (
    OpenAIFileSTTUpload,
    build_realtime_transcription_session_update,
    create_realtime_client_secret,
    realtime_websocket_url,
    transcribe_audio_file,
)


def test_build_realtime_transcription_session_update_uses_24khz_pcm():
    payload = build_realtime_transcription_session_update(
        model="gpt-realtime-whisper",
        language="en",
        turn_detection=None,
    )

    session = payload["session"]
    audio_input = session["audio"]["input"]
    assert session["type"] == "transcription"
    assert audio_input["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert audio_input["transcription"] == {
        "model": "gpt-realtime-whisper",
        "language": "en",
    }
    assert audio_input["turn_detection"] is None


@pytest.mark.asyncio
async def test_create_realtime_client_secret_posts_transcription_session():
    response = httpx.Response(
        200,
        json={"client_secret": {"value": "ek_test"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as mock_post,
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        token = await create_realtime_client_secret(
            model="gpt-realtime-whisper",
            language="multi",
        )

    assert token == "ek_test"
    kwargs = mock_post.await_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer sk-test"}
    assert kwargs["json"]["session"]["type"] == "transcription"
    transcription = kwargs["json"]["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-realtime-whisper"}


@pytest.mark.asyncio
async def test_create_realtime_client_secret_accepts_top_level_value():
    response = httpx.Response(
        200,
        json={"value": "ek_top_level"},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        token = await create_realtime_client_secret(
            model="gpt-realtime-whisper",
            language="en",
        )

    assert token == "ek_top_level"


@pytest.mark.asyncio
async def test_create_realtime_client_secret_rejects_invalid_secret_response():
    response = httpx.Response(
        200,
        json={"client_secret": {"id": "missing-value"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        with pytest.raises(RuntimeError, match="invalid realtime client secret"):
            await create_realtime_client_secret(
                model="gpt-realtime-whisper",
                language="multi",
            )


@pytest.mark.asyncio
async def test_create_realtime_client_secret_requires_openai_api_key():
    with patch("app.core.openai_transcription.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = ""
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await create_realtime_client_secret(
                model="gpt-realtime-whisper",
                language="multi",
            )


def test_realtime_websocket_url_uses_requested_model():
    assert (
        realtime_websocket_url("gpt-realtime-whisper")
        == "wss://api.openai.com/v1/realtime?model=gpt-realtime-whisper"
    )


@pytest.mark.asyncio
async def test_transcribe_audio_file_posts_diarized_json_request():
    response = httpx.Response(
        200,
        json={
            "text": "Hello there. General Kenobi.",
            "segments": [
                {"speaker": "speaker_0", "text": "Hello there.", "start": 0.0, "end": 1.25},
                {"speaker": "speaker_1", "text": "General Kenobi.", "start": 1.5, "end": 2.75},
            ],
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as mock_post,
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        result = await transcribe_audio_file(
            b"wav-data",
            language="ru-RU",
            content_type="audio/wav",
            model="gpt-4o-transcribe-diarize",
        )

    assert [item.text for item in result] == ["Hello there.", "General Kenobi."]
    assert [item.speaker for item in result] == ["speaker_0", "speaker_1"]
    assert [(item.start_ms, item.end_ms) for item in result] == [(0, 1250), (1500, 2750)]

    kwargs = mock_post.await_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer sk-test"}
    assert kwargs["data"] == {
        "model": "gpt-4o-transcribe-diarize",
        "response_format": "diarized_json",
        "chunking_strategy": "auto",
        "language": "ru",
    }
    assert kwargs["files"] == {
        "file": ("recording.wav", b"wav-data", "audio/wav"),
    }


@pytest.mark.asyncio
async def test_transcribe_audio_file_returns_empty_for_empty_diarized_segments():
    response = httpx.Response(
        200,
        json={"text": "", "segments": []},
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        result = await transcribe_audio_file(
            b"wav-data",
            content_type="audio/wav",
            model="gpt-4o-transcribe-diarize",
        )

    assert result == []


@pytest.mark.asyncio
async def test_transcribe_audio_file_offsets_chunked_upload_segments():
    responses = [
        httpx.Response(
            200,
            json={
                "text": "First chunk.",
                "segments": [
                    {"speaker": "A", "text": "First chunk.", "start": 0.0, "end": 1.0},
                ],
            },
            request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
        ),
        httpx.Response(
            200,
            json={
                "text": "Second chunk.",
                "segments": [
                    {"speaker": "B", "text": "Second chunk.", "start": 0.5, "end": 1.25},
                ],
            },
            request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
        ),
    ]

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch(
            "app.core.openai_transcription._prepare_file_stt_uploads",
            new=AsyncMock(
                return_value=[
                    OpenAIFileSTTUpload(
                        data=b"chunk-1",
                        content_type="audio/mpeg",
                        filename="recording-1.mp3",
                        offset_ms=0,
                    ),
                    OpenAIFileSTTUpload(
                        data=b"chunk-2",
                        content_type="audio/mpeg",
                        filename="recording-2.mp3",
                        offset_ms=3_600_000,
                    ),
                ]
            ),
        ) as mock_prepare,
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=responses)) as mock_post,
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        result = await transcribe_audio_file(
            b"large-wav-data",
            content_type="audio/wav",
            model="gpt-4o-transcribe-diarize",
        )

    mock_prepare.assert_awaited_once_with(b"large-wav-data", content_type="audio/wav")
    assert [item.text for item in result] == ["First chunk.", "Second chunk."]
    assert [(item.start_ms, item.end_ms) for item in result] == [
        (0, 1000),
        (3_600_500, 3_601_250),
    ]
    uploaded_files = [call.kwargs["files"]["file"] for call in mock_post.await_args_list]
    assert uploaded_files == [
        ("recording-1.mp3", b"chunk-1", "audio/mpeg"),
        ("recording-2.mp3", b"chunk-2", "audio/mpeg"),
    ]


@pytest.mark.asyncio
async def test_transcribe_audio_file_rejects_non_diarized_text_payload():
    response = httpx.Response(
        200,
        json={"text": "Hello without speaker segments."},
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        with pytest.raises(RuntimeError, match="invalid diarized transcription payload"):
            await transcribe_audio_file(
                b"wav-data",
                content_type="audio/wav",
                model="gpt-4o-transcribe-diarize",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_rejects_unsupported_content_type():
    with patch("app.core.openai_transcription.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = "sk-test"
        with pytest.raises(ValueError, match="Unsupported OpenAI STT content type"):
            await transcribe_audio_file(
                b"data",
                content_type="application/octet-stream",
                model="gpt-4o-transcribe-diarize",
            )


def test_file_stt_upload_filename_rejects_unsupported_content_type():
    from app.core.openai_transcription import _file_stt_upload_filename

    with pytest.raises(ValueError, match="Unsupported OpenAI STT content type"):
        _file_stt_upload_filename("audio/aac")


@pytest.mark.parametrize("language", ["", " auto ", "multi", "und"])
def test_file_stt_language_code_omits_auto_languages(language):
    from app.core.openai_transcription import _file_stt_language_code

    assert _file_stt_language_code(language) is None


def test_file_stt_language_code_normalizes_region_tag():
    from app.core.openai_transcription import _file_stt_language_code

    assert _file_stt_language_code("pt_BR") == "pt"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("plain text", "unexpected payload type=str"),
        ({"text": "   "}, ""),
    ],
)
def test_results_from_diarized_payload_handles_empty_or_invalid_payload(payload, message):
    from app.core.openai_transcription import _results_from_diarized_payload

    if message:
        with pytest.raises(RuntimeError, match=message):
            _results_from_diarized_payload(payload)
        return

    assert _results_from_diarized_payload(payload) == []


@pytest.mark.parametrize(
    ("segment", "message"),
    [
        ("not-a-dict", "invalid segment entry at index 0"),
        ({"text": 123, "start": 0, "end": 1}, "invalid segment text"),
        ({"text": "Hello", "speaker": 42, "start": 0, "end": 1}, "invalid segment speaker"),
        ({"text": "Hello", "start": "0", "end": 1}, "invalid segment start"),
    ],
)
def test_results_from_diarized_payload_rejects_malformed_segments(segment, message):
    from app.core.openai_transcription import _results_from_diarized_payload

    with pytest.raises(RuntimeError, match=message):
        _results_from_diarized_payload({"segments": [segment]})


def test_results_from_diarized_payload_skips_empty_segments_and_optional_speaker():
    from app.core.openai_transcription import _results_from_diarized_payload

    results = _results_from_diarized_payload(
        {
            "segments": [
                {"text": "   ", "start": 0, "end": 1},
                {"text": "Kept.", "speaker": "", "start": 1, "end": 2},
            ]
        }
    )

    assert len(results) == 1
    assert results[0].text == "Kept."
    assert results[0].speaker is None
    assert (results[0].start_ms, results[0].end_ms) == (1000, 2000)


def test_with_offset_returns_same_results_for_zero_offset():
    from app.core.openai_transcription import _with_offset
    from app.core.transcription import TranscriptResult

    results = [
        TranscriptResult(
            text="Hello",
            speaker=None,
            is_final=True,
            start_ms=0,
            end_ms=100,
            confidence=0.0,
        )
    ]

    assert _with_offset(results, 0) is results


def test_pydub_format_normalizes_wave_and_rejects_mov():
    from app.core.openai_transcription import _pydub_format

    assert _pydub_format("audio/wave; codecs=1") == "wav"
    assert _pydub_format("video/quicktime") is None


@pytest.mark.asyncio
async def test_prepare_file_stt_uploads_keeps_small_supported_upload_direct():
    from app.core.openai_transcription import _prepare_file_stt_uploads

    uploads = await _prepare_file_stt_uploads(
        b"wav-data",
        content_type="audio/wav; codecs=1",
    )

    assert uploads == [
        OpenAIFileSTTUpload(
            data=b"wav-data",
            content_type="audio/wav; codecs=1",
            filename="recording.wav",
            offset_ms=0,
        )
    ]


@pytest.mark.asyncio
async def test_prepare_file_stt_uploads_transcodes_large_supported_upload(monkeypatch):
    from app.core.openai_transcription import _prepare_file_stt_uploads

    calls = []

    def fake_transcoded_uploads(audio_data, content_type):
        calls.append((audio_data, content_type))
        return [
            OpenAIFileSTTUpload(
                data=b"mp3-data",
                content_type="audio/mpeg",
                filename="recording-1.mp3",
                offset_ms=0,
            )
        ]

    monkeypatch.setattr(
        "app.core.openai_transcription._transcoded_uploads",
        fake_transcoded_uploads,
    )
    monkeypatch.setattr("app.core.openai_transcription.OPENAI_MAX_TRANSCRIPTION_FILE_BYTES", 1)

    uploads = await _prepare_file_stt_uploads(b"large-wav-data", content_type="audio/wav")

    assert calls == [(b"large-wav-data", "audio/wav")]
    assert uploads == [
        OpenAIFileSTTUpload(
            data=b"mp3-data",
            content_type="audio/mpeg",
            filename="recording-1.mp3",
            offset_ms=0,
        )
    ]


def test_transcoded_uploads_chunks_audio_with_offsets(monkeypatch):
    from app.core.openai_transcription import _transcoded_uploads

    class FakeAudioSegment:
        loaded_format = None

        def __init__(self, duration_ms=2500):
            self.duration_ms = duration_ms

        @classmethod
        def from_file(cls, source, *, format):
            assert isinstance(source, BytesIO)
            cls.loaded_format = format
            return cls()

        def set_frame_rate(self, frame_rate):
            assert frame_rate == 16_000
            return self

        def set_channels(self, channels):
            assert channels == 1
            return self

        def __len__(self):
            return self.duration_ms

        def __getitem__(self, value):
            return FakeAudioSegment(value.stop - value.start)

        def export(self, output, *, format, bitrate):
            assert format == "mp3"
            assert bitrate == "24k"
            output.write(b"mp3")

    fake_pydub = SimpleNamespace(AudioSegment=FakeAudioSegment)
    monkeypatch.setitem(__import__("sys").modules, "pydub", fake_pydub)
    monkeypatch.setattr("app.core.openai_transcription.OPENAI_TRANSCODE_CHUNK_MS", 1000)
    monkeypatch.setattr("app.core.openai_transcription.OPENAI_MAX_TRANSCRIPTION_FILE_BYTES", 100)

    uploads = _transcoded_uploads(b"source-wav", "audio/wave")

    assert FakeAudioSegment.loaded_format == "wav"
    assert [(upload.filename, upload.offset_ms, upload.content_type) for upload in uploads] == [
        ("recording-1.mp3", 0, "audio/mpeg"),
        ("recording-2.mp3", 1000, "audio/mpeg"),
        ("recording-3.mp3", 2000, "audio/mpeg"),
    ]


def test_transcoded_uploads_rejects_oversized_chunk(monkeypatch):
    from app.core.openai_transcription import _transcoded_uploads

    class FakeAudioSegment:
        @classmethod
        def from_file(cls, source, *, format):
            return cls()

        def set_frame_rate(self, frame_rate):
            return self

        def set_channels(self, channels):
            return self

        def __len__(self):
            return 1

        def __getitem__(self, value):
            return self

        def export(self, output, *, format, bitrate):
            output.write(b"too-large")

    fake_pydub = SimpleNamespace(AudioSegment=FakeAudioSegment)
    monkeypatch.setitem(__import__("sys").modules, "pydub", fake_pydub)
    monkeypatch.setattr("app.core.openai_transcription.OPENAI_MAX_TRANSCRIPTION_FILE_BYTES", 1)

    with pytest.raises(RuntimeError, match="transcode chunk exceeded upload size limit"):
        _transcoded_uploads(b"source-wav", "audio/wav")
