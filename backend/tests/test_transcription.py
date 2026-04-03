"""Tests for the active transcription runtime."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_transcription_dispatches_to_elevenlabs():
    with (
        patch("app.core.transcription.get_settings") as mock_settings,
        patch(
            "app.core.transcription.elevenlabs_transcribe_audio_file",
            new=AsyncMock(return_value=["ok"]),
        ) as mock_elevenlabs,
    ):
        mock_settings.return_value.speech_to_text_provider = "elevenlabs"
        from app.core.transcription import transcribe_audio_file

        result = await transcribe_audio_file(b"audio", language="ru", content_type="audio/mp3")

    assert result == ["ok"]
    mock_elevenlabs.assert_awaited_once_with(
        b"audio",
        language="ru",
        content_type="audio/mp3",
        channels=None,
    )


@pytest.mark.asyncio
async def test_transcription_rejects_non_elevenlabs_provider():
    with patch("app.core.transcription.get_settings") as mock_settings:
        mock_settings.return_value.speech_to_text_provider = "unsupported-provider"
        from app.core.transcription import transcribe_audio_file

        with pytest.raises(ValueError, match="Only elevenlabs is supported"):
            await transcribe_audio_file(b"audio")
