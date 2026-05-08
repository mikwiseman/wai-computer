"""Provider-dispatched file transcription."""

from app.core.elevenlabs import transcribe_audio_file as elevenlabs_transcribe_audio_file
from app.core.inworld import transcribe_audio_file as inworld_transcribe_audio_file
from app.core.openai_transcription import transcribe_audio_file as openai_transcribe_audio_file
from app.core.transcript_utils import TranscriptResult
from app.core.transcription_options import (
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User


async def transcribe_audio_file(
    audio_data: bytes,
    language: str = "en",
    model: str = "nova-3",
    content_type: str = "audio/wav",
    channels: int | None = None,
    user: User | None = None,
) -> list[TranscriptResult]:
    """Transcribe audio using the active speech-to-text runtime."""
    provider = user.file_stt_provider if user is not None else DEFAULT_FILE_STT_PROVIDER
    selected_model = user.file_stt_model if user is not None else DEFAULT_FILE_STT_MODEL
    provider, selected_model = validate_option("file_stt", provider, selected_model)

    if provider == "openai":
        return await openai_transcribe_audio_file(
            audio_data,
            model=selected_model,
            language=language,
            content_type=content_type,
        )
    if provider == "inworld":
        return await inworld_transcribe_audio_file(
            audio_data,
            model=selected_model,
            language=language,
            content_type=content_type,
            channels=channels,
        )
    if provider != "elevenlabs":
        raise ValueError(f"Unsupported file_stt_provider: {provider}.")

    return await elevenlabs_transcribe_audio_file(
        audio_data,
        language=language,
        content_type=content_type,
        channels=channels,
        model=selected_model,
    )
