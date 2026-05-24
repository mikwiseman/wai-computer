"""Provider-dispatched file transcription."""

import logging
from io import BytesIO

import httpx

from app.config import get_settings
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

logger = logging.getLogger(__name__)

SONIOX_BROWSER_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/opus",
}

ELEVENLABS_DEEPGRAM_FALLBACK_STATUS_CODES = {401, 402, 403, 429, 500, 502, 503, 504}
ELEVENLABS_DEEPGRAM_FALLBACK_CODES = {
    "payment_issue",
    "payment_required",
    "quota_exceeded",
    "rate_limited",
    "service_unavailable",
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


def _elevenlabs_error_code(error: httpx.HTTPStatusError) -> str | None:
    try:
        payload = error.response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        for key in ("code", "type", "status"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _should_fallback_to_deepgram(error: httpx.HTTPStatusError) -> bool:
    status_code = error.response.status_code
    if status_code == 400:
        return False
    error_code = _elevenlabs_error_code(error)
    if error_code in ELEVENLABS_DEEPGRAM_FALLBACK_CODES:
        return True
    return status_code in ELEVENLABS_DEEPGRAM_FALLBACK_STATUS_CODES


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
    provider = provider or DEFAULT_FILE_STT_PROVIDER
    selected_model = model or DEFAULT_FILE_STT_MODEL
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

    try:
        return await elevenlabs_transcribe_audio_file(
            audio_data,
            language=language,
            content_type=content_type,
            channels=channels,
            model=selected_model,
        )
    except httpx.HTTPStatusError as exc:
        if not _should_fallback_to_deepgram(exc):
            raise
        fallback_model = get_settings().deepgram_file_stt_model
        error_code = _elevenlabs_error_code(exc) or "unknown"
        logger.warning(
            "falling back to Deepgram file STT primary_provider=elevenlabs "
            "fallback_provider=deepgram status_code=%s error_code=%s",
            exc.response.status_code,
            error_code,
        )
        return await deepgram_transcribe_audio_file(
            audio_data,
            model=fallback_model,
            language=language,
            content_type=content_type,
            channels=channels,
        )
