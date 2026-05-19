"""Provider-dispatched file transcription."""

from io import BytesIO

from app.core.deepgram import transcribe_audio_file as deepgram_transcribe_audio_file
from app.core.elevenlabs import transcribe_audio_file as elevenlabs_transcribe_audio_file
from app.core.soniox import transcribe_audio_file as soniox_transcribe_audio_file
from app.core.transcript_utils import TranscriptResult
from app.core.transcription_options import (
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

SONIOX_BROWSER_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/opus",
}


def _normalize_soniox_file_audio(
    audio_data: bytes,
    content_type: str,
    channels: int | None,
) -> tuple[bytes, str, int | None]:
    """Convert browser-recorded containers into WAV before Soniox async upload."""
    normalized_content_type = content_type.split(";")[0].strip().lower()
    if normalized_content_type not in SONIOX_BROWSER_AUDIO_CONTENT_TYPES:
        return audio_data, content_type, channels

    from pydub import AudioSegment

    try:
        segment = AudioSegment.from_file(BytesIO(audio_data))
    except Exception as exc:
        raise RuntimeError("Could not decode browser audio for Soniox transcription.") from exc

    segment = segment.set_frame_rate(16_000).set_channels(1).set_sample_width(2)
    output = BytesIO()
    segment.export(output, format="wav")
    return output.getvalue(), "audio/wav", 1


async def transcribe_audio_file(
    audio_data: bytes,
    language: str = "en",
    model: str | None = None,
    content_type: str = "audio/wav",
    channels: int | None = None,
    user: User | None = None,
    provider: str | None = None,
) -> list[TranscriptResult]:
    """Transcribe audio using the active speech-to-text runtime."""
    provider = provider or (
        user.file_stt_provider if user is not None else DEFAULT_FILE_STT_PROVIDER
    )
    selected_model = model or (
        user.file_stt_model if user is not None else DEFAULT_FILE_STT_MODEL
    )
    provider, selected_model = validate_option("file_stt", provider, selected_model)

    if provider == "deepgram":
        return await deepgram_transcribe_audio_file(
            audio_data,
            model=selected_model,
            language=language,
            content_type=content_type,
            channels=channels,
        )
    if provider == "soniox":
        audio_data, content_type, channels = _normalize_soniox_file_audio(
            audio_data,
            content_type,
            channels,
        )
        return await soniox_transcribe_audio_file(
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
