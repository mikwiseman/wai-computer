"""Provider-dispatched file transcription."""

import logging
import math
from io import BytesIO
from time import perf_counter

import httpx

from app.core.deepgram import transcribe_audio_file as deepgram_transcribe_audio_file
from app.core.elevenlabs import transcribe_audio_file as elevenlabs_transcribe_audio_file
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    fingerprint_text,
)
from app.core.soniox import transcribe_audio_file as soniox_transcribe_audio_file
from app.core.transcript_utils import TranscriptResult
from app.core.transcription_options import (
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

logger = logging.getLogger(__name__)
FILE_STT_SLOW_MIN_THRESHOLD_MS = 120_000
FILE_STT_AUDIO_DURATION_MULTIPLIER = 3.0

SONIOX_BROWSER_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/opus",
}


def file_stt_slow_threshold_ms(audio_duration_seconds: float | None) -> int:
    """Return the alert threshold for file STT latency."""
    if audio_duration_seconds is None or audio_duration_seconds <= 0:
        return FILE_STT_SLOW_MIN_THRESHOLD_MS
    duration_based_threshold = math.ceil(
        audio_duration_seconds * FILE_STT_AUDIO_DURATION_MULTIPLIER * 1000
    )
    return max(FILE_STT_SLOW_MIN_THRESHOLD_MS, duration_based_threshold)


def _latency_per_audio_second(
    *,
    latency_ms: int,
    audio_duration_seconds: float | None,
) -> float | None:
    if audio_duration_seconds is None or audio_duration_seconds <= 0:
        return None
    return round((latency_ms / 1000) / audio_duration_seconds, 4)


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


async def transcribe_audio_file(
    audio_data: bytes,
    language: str = "en",
    model: str | None = None,
    content_type: str = "audio/wav",
    channels: int | None = None,
    user: User | None = None,
    provider: str | None = None,
    audio_duration_seconds: float | None = None,
) -> list[TranscriptResult]:
    """Transcribe audio using the active speech-to-text runtime."""
    provider = provider or DEFAULT_FILE_STT_PROVIDER
    selected_model = model or DEFAULT_FILE_STT_MODEL
    provider, selected_model = validate_option("file_stt", provider, selected_model)
    started_at = perf_counter()
    audio_bytes = len(audio_data)
    add_sentry_breadcrumb(
        category="recording",
        message="File transcription started",
        data={
            "provider": provider,
            "model": selected_model,
            "audio_bytes": audio_bytes,
            "content_type": content_type,
            "channels": channels,
            "audio_duration_seconds": audio_duration_seconds,
        },
    )

    try:
        if provider == "deepgram":
            results = await deepgram_transcribe_audio_file(
                audio_data,
                model=selected_model,
                language=language,
                content_type=content_type,
                channels=channels,
            )
        elif provider == "soniox":
            audio_data, content_type, channels = _normalize_soniox_file_audio(
                audio_data,
                content_type,
                channels,
            )
            results = await soniox_transcribe_audio_file(
                audio_data,
                model=selected_model,
                language=language,
                content_type=content_type,
                channels=channels,
            )
        elif provider == "elevenlabs":
            results = await elevenlabs_transcribe_audio_file(
                audio_data,
                language=language,
                content_type=content_type,
                channels=channels,
                model=selected_model,
            )
        else:
            raise ValueError(f"Unsupported file_stt_provider: {provider}.")
    except httpx.HTTPStatusError as exc:
        error_code = _elevenlabs_error_code(exc) or "unknown"
        latency_ms = round((perf_counter() - started_at) * 1000)
        logger.warning(
            "file STT failed provider=%s model=%s latency_ms=%s status_code=%s "
            "error_code=%s error_fingerprint=%s audio_bytes=%s content_type=%s channels=%s",
            provider,
            selected_model,
            latency_ms,
            exc.response.status_code,
            error_code,
            fingerprint_text(exc.response.text),
            audio_bytes,
            content_type,
            channels,
        )
        raise
    except Exception as exc:
        latency_ms = round((perf_counter() - started_at) * 1000)
        logger.exception(
            "file STT failed provider=%s model=%s latency_ms=%s error_type=%s "
            "audio_bytes=%s content_type=%s channels=%s",
            provider,
            selected_model,
            latency_ms,
            type(exc).__name__,
            audio_bytes,
            content_type,
            channels,
        )
        raise

    latency_ms = round((perf_counter() - started_at) * 1000)
    threshold_ms = file_stt_slow_threshold_ms(audio_duration_seconds)
    completion_data = {
        "provider": provider,
        "model": selected_model,
        "latency_ms": latency_ms,
        "slow_threshold_ms": threshold_ms,
        "audio_duration_seconds": audio_duration_seconds,
        "latency_per_audio_second": _latency_per_audio_second(
            latency_ms=latency_ms,
            audio_duration_seconds=audio_duration_seconds,
        ),
        "audio_bytes": audio_bytes,
        "content_type": content_type,
        "channels": channels,
        "segment_count": len(results),
    }
    logger.info(
        "file STT completed provider=%s model=%s latency_ms=%s segment_count=%s "
        "audio_bytes=%s content_type=%s channels=%s",
        provider,
        selected_model,
        latency_ms,
        len(results),
        audio_bytes,
        content_type,
        channels,
    )
    add_sentry_breadcrumb(
        category="recording",
        message="File transcription completed",
        data=completion_data,
    )
    if latency_ms >= threshold_ms:
        capture_sentry_anomaly(
            "recording.file_stt.slow",
            "File transcription latency exceeded threshold",
            category="recording",
            extras=completion_data,
        )
    return results
