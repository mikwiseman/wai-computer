"""Tests for the active transcription runtime."""

from unittest.mock import AsyncMock, patch

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
async def test_transcription_dispatches_to_deepgram_for_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "deepgram", "file_stt_model": "nova-3"},
    )()
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(return_value=["deepgram-ok"]),
    ) as mock_deepgram:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["deepgram-ok"]
    mock_deepgram.assert_awaited_once_with(
        b"audio",
        model="nova-3",
        language="en",
        content_type="audio/wav",
        channels=1,
    )


@pytest.mark.asyncio
async def test_transcription_dispatches_to_soniox_for_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "soniox", "file_stt_model": "stt-async-v4"},
    )()
    with patch(
        "app.core.transcription.soniox_transcribe_audio_file",
        new=AsyncMock(return_value=["soniox-ok"]),
    ) as mock_soniox:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["soniox-ok"]
    mock_soniox.assert_awaited_once_with(
        b"audio",
        model="stt-async-v4",
        language="en",
        content_type="audio/wav",
        channels=1,
    )


@pytest.mark.asyncio
async def test_transcription_normalizes_browser_audio_before_soniox_file_stt():
    with (
        patch(
            "app.core.transcription._normalize_soniox_file_audio",
            return_value=(b"wav-data", "audio/wav", 1),
        ) as mock_normalize,
        patch(
            "app.core.transcription.soniox_transcribe_audio_file",
            new=AsyncMock(return_value=["soniox-ok"]),
        ) as mock_soniox,
    ):
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"webm-data",
            language="en",
            content_type="audio/webm",
            provider="soniox",
            model="stt-async-v4",
        )

    assert result == ["soniox-ok"]
    mock_normalize.assert_called_once_with(b"webm-data", "audio/webm", None)
    mock_soniox.assert_awaited_once_with(
        b"wav-data",
        model="stt-async-v4",
        language="en",
        content_type="audio/wav",
        channels=1,
    )


@pytest.mark.asyncio
async def test_transcription_dispatches_to_explicit_provider_and_model_without_user():
    with patch(
        "app.core.transcription.deepgram_transcribe_audio_file",
        new=AsyncMock(return_value=["deepgram-ok"]),
    ) as mock_deepgram:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="deepgram",
            model="nova-3",
        )

    assert result == ["deepgram-ok"]
    mock_deepgram.assert_awaited_once_with(
        b"audio",
        model="nova-3",
        language="en",
        content_type="audio/wav",
        channels=None,
    )


@pytest.mark.asyncio
async def test_transcription_rejects_dropped_openai_models():
    """OpenAI file transcription is no longer a valid file STT choice."""
    user = type(
        "User",
        (),
        {"file_stt_provider": "openai", "file_stt_model": "retired-batch-stt"},
    )()
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(b"audio", user=user)


@pytest.mark.asyncio
async def test_transcription_rejects_unsupported_user_choice():
    user = type("User", (), {"file_stt_provider": "elevenlabs", "file_stt_model": "bad-model"})()
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(b"audio", user=user)


def test_normalize_soniox_file_audio_leaves_non_browser_audio_unchanged():
    from app.core.transcription import _normalize_soniox_file_audio

    assert _normalize_soniox_file_audio(b"wav", "audio/wav; codecs=1", 2) == (
        b"wav",
        "audio/wav; codecs=1",
        2,
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
