"""Tests for the active transcription runtime."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_transcription_dispatches_to_elevenlabs():
    with (
        patch(
            "app.core.transcription.elevenlabs_transcribe_audio_file",
            new=AsyncMock(return_value=["ok"]),
        ) as mock_elevenlabs,
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", language="ru", content_type="audio/mp3")

    assert result == ["ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="ru",
        content_type="audio/mp3",
        channels=None,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_ignores_deepgram_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "deepgram", "file_stt_model": "nova-3"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ) as mock_elevenlabs:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["elevenlabs-ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="en",
        content_type="audio/wav",
        channels=1,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_ignores_soniox_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "soniox", "file_stt_model": "stt-async-v4"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ) as mock_elevenlabs:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["elevenlabs-ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="en",
        content_type="audio/wav",
        channels=1,
        model="scribe_v2",
    )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_soniox_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"webm-data",
            language="en",
            content_type="audio/webm",
            provider="soniox",
            model="stt-async-v4",
        )


@pytest.mark.asyncio
async def test_transcription_rejects_explicit_deepgram_file_stt():
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="deepgram",
            model="nova-3",
        )


@pytest.mark.asyncio
async def test_transcription_ignores_dropped_openai_user_choice():
    """User-persisted file STT choices no longer select the runtime model."""
    user = type(
        "User",
        (),
        {"file_stt_provider": "openai", "file_stt_model": "retired-batch-stt"},
    )()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", user=user)

    assert result == ["elevenlabs-ok"]


@pytest.mark.asyncio
async def test_transcription_ignores_unsupported_user_choice():
    user = type("User", (), {"file_stt_provider": "elevenlabs", "file_stt_model": "bad-model"})()
    with patch(
        "app.core.transcription.elevenlabs_transcribe_audio_file",
        new=AsyncMock(return_value=["elevenlabs-ok"]),
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", user=user)

    assert result == ["elevenlabs-ok"]


@pytest.mark.asyncio
async def test_transcription_falls_back_to_deepgram_for_elevenlabs_payment_issue(caplog):
    response = httpx.Response(
        401,
        json={
            "detail": {
                "type": "payment_required",
                "code": "payment_issue",
                "message": "Complete the latest invoice to continue usage.",
            }
        },
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    error = httpx.HTTPStatusError(
        "Client error '401 Unauthorized'",
        request=response.request,
        response=response,
    )
    deepgram = AsyncMock(return_value=["deepgram-ok"])

    with (
        patch(
            "app.core.transcription.elevenlabs_transcribe_audio_file",
            new=AsyncMock(side_effect=error),
        ),
        patch("app.core.transcription.deepgram_transcribe_audio_file", new=deepgram),
        patch("app.core.transcription.get_settings") as mock_settings,
        caplog.at_level("WARNING", logger="app.core.transcription"),
    ):
        mock_settings.return_value.deepgram_file_stt_model = "nova-3"
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"wav",
            language="auto",
            content_type="audio/wav",
            channels=1,
        )

    assert result == ["deepgram-ok"]
    deepgram.assert_awaited_once_with(
        b"wav",
        model="nova-3",
        language="auto",
        content_type="audio/wav",
        channels=1,
    )
    assert "falling back to Deepgram file STT" in caplog.text
    assert "Complete the latest invoice" not in caplog.text


@pytest.mark.asyncio
async def test_transcription_does_not_fallback_for_elevenlabs_bad_request():
    response = httpx.Response(
        400,
        json={"detail": {"message": "Invalid language_code"}},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    error = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=response.request,
        response=response,
    )
    deepgram = AsyncMock(return_value=["deepgram-ok"])

    with (
        patch(
            "app.core.transcription.elevenlabs_transcribe_audio_file",
            new=AsyncMock(side_effect=error),
        ),
        patch("app.core.transcription.deepgram_transcribe_audio_file", new=deepgram),
    ):
        from app.core.transcription import transcribe_audio_file

        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_file(b"wav", language="auto", content_type="audio/wav")

    deepgram.assert_not_awaited()


def test_elevenlabs_error_code_handles_unstructured_error_payloads():
    from app.core.transcription import _elevenlabs_error_code, _should_fallback_to_deepgram

    invalid_json_response = httpx.Response(
        503,
        content=b"not-json",
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    invalid_json_error = httpx.HTTPStatusError(
        "Service unavailable",
        request=invalid_json_response.request,
        response=invalid_json_response,
    )
    assert _elevenlabs_error_code(invalid_json_error) is None
    assert _should_fallback_to_deepgram(invalid_json_error)

    list_response = httpx.Response(
        401,
        json=["bad"],
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    list_error = httpx.HTTPStatusError(
        "Unauthorized",
        request=list_response.request,
        response=list_response,
    )
    assert _elevenlabs_error_code(list_error) is None

    detail_response = httpx.Response(
        402,
        json={"detail": {"status": "payment_issue"}},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text"),
    )
    detail_error = httpx.HTTPStatusError(
        "Payment required",
        request=detail_response.request,
        response=detail_response,
    )
    assert _elevenlabs_error_code(detail_error) == "payment_issue"


@pytest.mark.asyncio
async def test_transcription_deepgram_branch_remains_dispatchable(monkeypatch):
    monkeypatch.setattr(
        "app.core.transcription.validate_option",
        lambda _kind, _provider, _model: ("deepgram", "nova-3"),
    )
    deepgram = AsyncMock(return_value=["deepgram-ok"])
    monkeypatch.setattr("app.core.transcription.deepgram_transcribe_audio_file", deepgram)
    from app.core.transcription import transcribe_audio_file

    result = await transcribe_audio_file(
        b"audio",
        language="ru",
        content_type="audio/wav",
        channels=2,
        provider="deepgram",
        model="nova-3",
    )

    assert result == ["deepgram-ok"]
    deepgram.assert_awaited_once_with(
        b"audio",
        model="nova-3",
        language="ru",
        content_type="audio/wav",
        channels=2,
    )


@pytest.mark.asyncio
async def test_transcription_soniox_branch_normalizes_browser_audio(monkeypatch):
    monkeypatch.setattr(
        "app.core.transcription.validate_option",
        lambda _kind, _provider, _model: ("soniox", "stt-async-v4"),
    )
    monkeypatch.setattr(
        "app.core.transcription._normalize_soniox_file_audio",
        lambda _audio, _content_type, _channels: (b"wav", "audio/wav", 1),
    )
    soniox = AsyncMock(return_value=["soniox-ok"])
    monkeypatch.setattr("app.core.transcription.soniox_transcribe_audio_file", soniox)
    from app.core.transcription import transcribe_audio_file

    result = await transcribe_audio_file(
        b"webm",
        language="auto",
        content_type="audio/webm",
        provider="soniox",
        model="stt-async-v4",
    )

    assert result == ["soniox-ok"]
    soniox.assert_awaited_once_with(
        b"wav",
        model="stt-async-v4",
        language="auto",
        content_type="audio/wav",
        channels=1,
    )


def test_normalize_soniox_file_audio_leaves_non_browser_audio_unchanged():
    from app.core.transcription import _normalize_soniox_file_audio

    assert _normalize_soniox_file_audio(b"wav", "audio/wav; codecs=1", 2) == (
        b"wav",
        "audio/wav; codecs=1",
        2,
    )


def test_normalize_soniox_file_audio_converts_browser_audio(monkeypatch):
    from app.core.transcription import _normalize_soniox_file_audio

    class FakeSegment:
        def set_frame_rate(self, value):
            assert value == 16_000
            return self

        def set_channels(self, value):
            assert value == 1
            return self

        def set_sample_width(self, value):
            assert value == 2
            return self

        def export(self, output, format):
            assert format == "wav"
            output.write(b"wav")

    monkeypatch.setattr("pydub.AudioSegment.from_file", lambda _data: FakeSegment())

    assert _normalize_soniox_file_audio(b"webm", " audio/webm ;codecs=opus", None) == (
        b"wav",
        "audio/wav",
        1,
    )


def test_normalize_soniox_file_audio_surfaces_decode_errors():
    from app.core.transcription import _normalize_soniox_file_audio

    with pytest.raises(RuntimeError, match="Could not decode browser audio"):
        _normalize_soniox_file_audio(b"not-a-real-webm", " audio/webm ;codecs=opus", None)


@pytest.mark.asyncio
async def test_transcription_rejects_provider_left_after_validation(monkeypatch):
    monkeypatch.setattr(
        "app.core.transcription.validate_option",
        lambda _kind, _provider, _model: ("bogus", "model"),
    )
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt_provider: bogus"):
        await transcribe_audio_file(b"audio", provider="elevenlabs", model="scribe_v2")
