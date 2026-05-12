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
async def test_transcription_dispatches_to_openai_for_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "openai", "file_stt_model": "gpt-4o-transcribe"},
    )()
    with patch(
        "app.core.transcription.openai_transcribe_audio_file",
        new=AsyncMock(return_value=["openai-ok"]),
    ) as mock_openai:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            user=user,
        )

    assert result == ["openai-ok"]
    mock_openai.assert_awaited_once_with(
        b"audio",
        model="gpt-4o-transcribe",
        language="en",
        content_type="audio/wav",
    )


@pytest.mark.asyncio
async def test_transcription_dispatches_to_explicit_provider_and_model_without_user():
    with patch(
        "app.core.transcription.openai_transcribe_audio_file",
        new=AsyncMock(return_value=["openai-ok"]),
    ) as mock_openai:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            provider="openai",
            model="gpt-4o-transcribe",
        )

    assert result == ["openai-ok"]
    mock_openai.assert_awaited_once_with(
        b"audio",
        model="gpt-4o-transcribe",
        language="en",
        content_type="audio/wav",
    )


@pytest.mark.asyncio
async def test_transcription_dispatches_to_inworld_for_user_choice():
    user = type(
        "User",
        (),
        {"file_stt_provider": "inworld", "file_stt_model": "inworld/inworld-stt-1"},
    )()
    with patch(
        "app.core.transcription.inworld_transcribe_audio_file",
        new=AsyncMock(return_value=["inworld-ok"]),
    ) as mock_inworld:
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(
            b"audio",
            language="en",
            content_type="audio/wav",
            channels=1,
            user=user,
        )

    assert result == ["inworld-ok"]
    mock_inworld.assert_awaited_once_with(
        b"audio",
        model="inworld/inworld-stt-1",
        language="en",
        content_type="audio/wav",
        channels=1,
    )


@pytest.mark.asyncio
async def test_transcription_rejects_unsupported_user_choice():
    user = type("User", (), {"file_stt_provider": "openai", "file_stt_model": "bad-model"})()
    from app.core.transcription import transcribe_audio_file

    with pytest.raises(ValueError, match="Unsupported file_stt option"):
        await transcribe_audio_file(b"audio", user=user)
