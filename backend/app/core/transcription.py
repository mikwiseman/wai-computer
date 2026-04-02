"""ElevenLabs-backed file transcription."""

from app.config import get_settings
from app.core.elevenlabs import transcribe_audio_file as elevenlabs_transcribe_audio_file
from app.core.transcript_utils import TranscriptResult


async def transcribe_audio_file(
    audio_data: bytes,
    language: str = "en",
    model: str = "nova-3",
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe audio using the active speech-to-text runtime."""
    provider = get_settings().speech_to_text_provider.strip().lower()
    if provider != "elevenlabs":
        raise ValueError(
            f"Unsupported speech_to_text_provider: {provider}. "
            "Only elevenlabs is supported."
        )
    return await elevenlabs_transcribe_audio_file(
        audio_data,
        language=language,
        content_type=content_type,
        channels=channels,
    )
