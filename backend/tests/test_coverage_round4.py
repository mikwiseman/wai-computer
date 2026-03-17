"""Round 4 coverage tests — folders routes + deepgram core."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.core.deepgram as deepgram_module
from app.core.deepgram import (
    DeepgramStreamingClient,
    detect_wav_channels,
    transcribe_audio_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_folder(client: AsyncClient, headers: dict, name: str = "Work") -> dict:
    resp = await client.post("/api/folders", headers=headers, json={"name": name})
    assert resp.status_code == 201
    return resp.json()


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Rec",
    folder_id: str | None = None,
) -> dict:
    payload: dict[str, str | None] = {"title": title, "type": "note", "language": "en"}
    if folder_id is not None:
        payload["folder_id"] = folder_id
    resp = await client.post("/api/recordings", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


def _wav_header(channels: int = 1) -> bytes:
    """Build a minimal 44-byte WAV header with the given channel count."""
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = channels.to_bytes(2, "little")
    return bytes(header)


class _AsyncWSIterator:
    """Async iterator that yields JSON messages, like a websocket."""

    def __init__(self, messages: list[str]):
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


def _mock_httpx_client(response_json: dict) -> AsyncMock:
    """Return a mock httpx.AsyncClient whose post() returns *response_json*."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ===========================================================================
# FOLDER ROUTE TESTS
# ===========================================================================


@pytest.mark.asyncio
async def test_update_folder_name(client: AsyncClient, auth_headers: dict):
    """PATCH /api/folders/:id updates the folder name and returns the updated object."""
    folder = await _create_folder(client, auth_headers, name="Original")

    resp = await client.patch(
        f"/api/folders/{folder['id']}",
        headers=auth_headers,
        json={"name": "Renamed"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["id"] == folder["id"]

    # Confirm persistence via list
    list_resp = await client.get("/api/folders", headers=auth_headers)
    names = [f["name"] for f in list_resp.json()]
    assert "Renamed" in names
    assert "Original" not in names


@pytest.mark.asyncio
async def test_update_folder_empty_name_returns_422(client: AsyncClient, auth_headers: dict):
    """PATCH /api/folders/:id with an empty (whitespace-only) name returns 422."""
    folder = await _create_folder(client, auth_headers, name="Valid")

    resp = await client.patch(
        f"/api/folders/{folder['id']}",
        headers=auth_headers,
        json={"name": "   "},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_folder_unassigns_recordings(client: AsyncClient, auth_headers: dict):
    """DELETE /api/folders/:id sets folder_id to None on all assigned recordings."""
    folder = await _create_folder(client, auth_headers, name="Temporary")
    rec1 = await _create_recording(client, auth_headers, title="A", folder_id=folder["id"])
    rec2 = await _create_recording(client, auth_headers, title="B", folder_id=folder["id"])
    # A recording in no folder — should be unaffected
    rec3 = await _create_recording(client, auth_headers, title="C")

    delete_resp = await client.delete(f"/api/folders/{folder['id']}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Both assigned recordings should now have folder_id == None
    for rec_id in (rec1["id"], rec2["id"]):
        detail = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
        assert detail.status_code == 200
        assert detail.json()["folder_id"] is None

    # Unrelated recording still fine
    detail3 = await client.get(f"/api/recordings/{rec3['id']}", headers=auth_headers)
    assert detail3.status_code == 200
    assert detail3.json()["folder_id"] is None


@pytest.mark.asyncio
async def test_create_duplicate_folder_name_succeeds(client: AsyncClient, auth_headers: dict):
    """Creating two folders with the same name should succeed (no unique constraint)."""
    f1 = await _create_folder(client, auth_headers, name="Duplicated")
    f2 = await _create_folder(client, auth_headers, name="Duplicated")

    assert f1["id"] != f2["id"]
    assert f1["name"] == f2["name"] == "Duplicated"

    list_resp = await client.get("/api/folders", headers=auth_headers)
    names = [f["name"] for f in list_resp.json()]
    assert names.count("Duplicated") == 2


@pytest.mark.asyncio
async def test_list_folders_returns_empty_for_new_user(client: AsyncClient, auth_headers: dict):
    """A fresh user with zero folders gets an empty JSON array."""
    resp = await client.get("/api/folders", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ===========================================================================
# DEEPGRAM CORE TESTS
# ===========================================================================


@pytest.fixture(autouse=True)
def _patch_deepgram_settings():
    """Ensure every deepgram test in this file has a fake API key."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", "dg-round4-key"):
        yield


@pytest.mark.asyncio
async def test_parse_multichannel_response_filters_empty_sentences():
    """Multichannel paragraphs with empty sentence text should be silently skipped."""
    wav_data = _wav_header(channels=2) + b"\x00" * 100

    deepgram_response = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "confidence": 0.9,
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "sentences": [
                                            {"text": "Good morning.", "start": 0.0, "end": 1.0},
                                            {"text": "", "start": 1.0, "end": 1.5},
                                            {"text": "   ", "start": 1.5, "end": 2.0},
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "alternatives": [
                        {
                            "confidence": 0.88,
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "sentences": [
                                            {"text": "", "start": 0.0, "end": 0.5},
                                            {"text": "Hi there!", "start": 0.5, "end": 1.2},
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                },
            ]
        }
    }

    mock_client = _mock_httpx_client(deepgram_response)
    with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
        results = await transcribe_audio_file(wav_data, content_type="audio/wav")

    # Only non-empty, non-whitespace sentences survive
    assert len(results) == 2
    texts = [r.text for r in results]
    assert "Good morning." in texts
    assert "Hi there!" in texts
    # Empty and whitespace-only sentences are gone
    assert "" not in texts


@pytest.mark.asyncio
async def test_parse_single_channel_utterances():
    """Single-channel mode parses utterances with correct speaker labels and timing."""
    deepgram_response = {
        "results": {
            "utterances": [
                {
                    "transcript": "First sentence.",
                    "speaker": 0,
                    "start": 0.0,
                    "end": 2.0,
                    "confidence": 0.97,
                },
                {
                    "transcript": "Second sentence.",
                    "speaker": 1,
                    "start": 2.5,
                    "end": 4.0,
                    "confidence": 0.93,
                },
                {
                    "transcript": "Third sentence.",
                    "speaker": 0,
                    "start": 4.5,
                    "end": 6.0,
                    "confidence": 0.91,
                },
            ]
        }
    }

    mock_client = _mock_httpx_client(deepgram_response)
    # Use non-WAV content type to force single-channel path
    with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
        results = await transcribe_audio_file(
            b"fake-audio", content_type="audio/mpeg"
        )

    assert len(results) == 3
    assert results[0].text == "First sentence."
    assert results[0].speaker == "Speaker 0"
    assert results[0].start_ms == 0
    assert results[0].end_ms == 2000
    assert results[0].confidence == 0.97
    assert results[0].is_final is True

    assert results[1].speaker == "Speaker 1"
    assert results[1].start_ms == 2500

    assert results[2].speaker == "Speaker 0"
    assert results[2].start_ms == 4500
    assert results[2].end_ms == 6000


def test_wav_channel_detection_stereo():
    """detect_wav_channels returns 2 for a stereo WAV header."""
    assert detect_wav_channels(_wav_header(channels=2)) == 2


def test_wav_channel_detection_mono():
    """detect_wav_channels returns 1 for a mono WAV header."""
    assert detect_wav_channels(_wav_header(channels=1)) == 1


@pytest.mark.asyncio
async def test_malformed_deepgram_response_returns_empty():
    """A response with no 'results' key returns an empty list without crashing."""
    mock_client = _mock_httpx_client({"metadata": {"request_id": "abc"}})
    with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
        results = await transcribe_audio_file(b"audio-data", content_type="audio/mpeg")

    assert results == []


@pytest.mark.asyncio
async def test_transcribe_missing_api_key_raises_error():
    """transcribe_audio_file raises ValueError when deepgram_api_key is empty."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", ""):
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await transcribe_audio_file(b"some-audio")


@pytest.mark.asyncio
async def test_rest_transcription_mocked_response_parsing():
    """Full round-trip: REST transcription with paragraphs in multichannel mode."""
    wav_data = _wav_header(channels=2) + b"\x00" * 50

    deepgram_response = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "confidence": 0.96,
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "sentences": [
                                            {"text": "Let me explain.", "start": 0.0, "end": 1.5},
                                            {"text": "It works like this.",
                                             "start": 1.6, "end": 3.0},
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "alternatives": [
                        {
                            "confidence": 0.91,
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "sentences": [
                                            {"text": "I see, go on.", "start": 1.0, "end": 2.0},
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                },
            ]
        }
    }

    mock_client = _mock_httpx_client(deepgram_response)
    with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
        results = await transcribe_audio_file(wav_data, content_type="audio/wav")

    assert len(results) == 3

    # Sorted by start_ms
    assert results[0].text == "Let me explain."
    assert results[0].speaker == "You"  # ch0
    assert results[0].start_ms == 0
    assert results[0].end_ms == 1500

    assert results[1].text == "I see, go on."
    assert results[1].speaker == "Speaker 1"  # ch1
    assert results[1].start_ms == 1000
    assert results[1].end_ms == 2000

    assert results[2].text == "It works like this."
    assert results[2].speaker == "You"  # ch0
    assert results[2].start_ms == 1600
    assert results[2].end_ms == 3000

    # Verify multichannel params
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["params"]["multichannel"] == "true"
    assert call_kwargs.kwargs["params"]["channels"] == "2"


@pytest.mark.asyncio
async def test_streaming_connect_missing_api_key_raises():
    """DeepgramStreamingClient.connect() raises ValueError when key is absent."""
    with patch.object(deepgram_module.settings, "deepgram_api_key", ""):
        client = DeepgramStreamingClient()
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            await client.connect()


@pytest.mark.asyncio
async def test_finish_stream_sends_close_message():
    """finish_stream() sends a CloseStream JSON message to the websocket."""
    mock_ws = AsyncMock()
    client = DeepgramStreamingClient()
    client._ws = mock_ws
    client._running = True

    await client.finish_stream()

    mock_ws.send.assert_called_once_with(json.dumps({"type": "CloseStream"}))


@pytest.mark.asyncio
async def test_finish_stream_noop_when_not_running():
    """finish_stream() does nothing when client is not running."""
    mock_ws = AsyncMock()
    client = DeepgramStreamingClient()
    client._ws = mock_ws
    client._running = False

    await client.finish_stream()

    mock_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_receive_transcripts_skips_empty_transcript():
    """receive_transcripts skips Results messages where transcript is empty string."""
    empty_msg = json.dumps({
        "type": "Results",
        "is_final": True,
        "channel": {
            "alternatives": [
                {"transcript": "", "confidence": 0.0, "words": []}
            ]
        },
    })
    real_msg = json.dumps({
        "type": "Results",
        "is_final": True,
        "channel": {
            "alternatives": [
                {
                    "transcript": "Actual speech.",
                    "confidence": 0.9,
                    "words": [
                        {"word": "Actual", "speaker": 0, "start": 0.0, "end": 0.3},
                        {"word": "speech", "speaker": 0, "start": 0.3, "end": 0.6},
                    ],
                }
            ]
        },
    })

    ws_iter = _AsyncWSIterator([empty_msg, real_msg])
    ws_iter.close = AsyncMock()

    streaming = DeepgramStreamingClient()
    streaming._ws = ws_iter
    streaming._running = True

    results = []
    async for r in streaming.receive_transcripts():
        results.append(r)

    assert len(results) == 1
    assert results[0].text == "Actual speech."


@pytest.mark.asyncio
async def test_multichannel_fallback_to_full_transcript():
    """Multichannel: when paragraphs are absent, falls back to the full channel transcript."""
    wav_data = _wav_header(channels=2) + b"\x00" * 50

    deepgram_response = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Full transcript channel zero.",
                            "confidence": 0.88,
                            "words": [
                                {"word": "Full", "start": 0.0, "end": 0.3},
                                {"word": "transcript", "start": 0.3, "end": 0.7},
                                {"word": "channel", "start": 0.7, "end": 1.0},
                                {"word": "zero", "start": 1.0, "end": 1.2},
                            ],
                            # No paragraphs key
                        }
                    ]
                },
                {
                    "alternatives": [
                        {
                            "transcript": "Channel one text.",
                            "confidence": 0.85,
                            "words": [
                                {"word": "Channel", "start": 0.5, "end": 0.8},
                                {"word": "one", "start": 0.8, "end": 1.0},
                                {"word": "text", "start": 1.0, "end": 1.3},
                            ],
                        }
                    ]
                },
            ]
        }
    }

    mock_client = _mock_httpx_client(deepgram_response)
    with patch("app.core.deepgram.httpx.AsyncClient", return_value=mock_client):
        results = await transcribe_audio_file(wav_data, content_type="audio/wav")

    assert len(results) == 2
    # Sorted by start_ms: ch0 at 0ms, ch1 at 500ms
    assert results[0].text == "Full transcript channel zero."
    assert results[0].speaker == "You"
    assert results[0].start_ms == 0
    assert results[0].end_ms == 1200

    assert results[1].text == "Channel one text."
    assert results[1].speaker == "Speaker 1"
    assert results[1].start_ms == 500
    assert results[1].end_ms == 1300
