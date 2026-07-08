"""Provider-dispatched file transcription."""

import logging
import math
from time import perf_counter

import httpx

from app.config import get_settings
from app.core.deepgram import transcribe_audio_file as deepgram_transcribe_audio_file
from app.core.elevenlabs_stt import (
    transcribe_audio_file as elevenlabs_transcribe_audio_file,
)
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    fingerprint_text,
)
from app.core.transcript_utils import TranscriptResult
from app.core.transcription_guard import (
    TranscriptionGuardError,
    check_minutes_budget,
    provider_breaker_open,
    record_minutes,
    record_provider_result,
    transcription_halted,
)
from app.core.transcription_options import (
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

logger = logging.getLogger(__name__)
FILE_STT_SLOW_MIN_THRESHOLD_MS = 120_000
FILE_STT_AUDIO_DURATION_MULTIPLIER = 3.0


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


def _provider_error_code(error: httpx.HTTPStatusError) -> str | None:
    try:
        payload = error.response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    openai_error = payload.get("error")
    if isinstance(openai_error, dict):
        for key in ("code", "type"):
            value = openai_error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        for key in ("code", "type", "status"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("err_code", "category", "code", "type", "status"):
        value = payload.get(key)
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
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
    user_id: str | None = None,
    usage_purpose: str | None = None,
) -> list[TranscriptResult]:
    """Transcribe audio using the active speech-to-text runtime.

    Single batch choke point: every file-STT entrypoint (native uploads, Telegram
    voice notes, imports) flows through here, so the provider cost/abuse guards
    (kill-switch, circuit breaker, max-duration, daily minute budget, breaker-feed
    and minute-metering) live here once instead of per-entrypoint.
    """
    provider = provider or DEFAULT_FILE_STT_PROVIDER
    selected_model = model or DEFAULT_FILE_STT_MODEL
    provider, selected_model = validate_option("file_stt", provider, selected_model)
    if provider not in {"elevenlabs", "deepgram"}:
        raise ValueError(f"Unsupported file_stt_provider: {provider}.")

    settings = get_settings()
    guard_user_id = user_id or (str(getattr(user, "id", "")) if user is not None else "")
    guard_user_id = guard_user_id or "anonymous"
    estimated_minutes = (audio_duration_seconds or 0.0) / 60.0
    if await transcription_halted():
        raise TranscriptionGuardError(
            "transcription_halted", "Transcription is temporarily disabled."
        )
    if await provider_breaker_open():
        raise TranscriptionGuardError(
            "provider_unavailable", "Transcription provider is temporarily unavailable."
        )
    max_seconds = settings.recording_max_audio_seconds
    if (
        max_seconds > 0
        and audio_duration_seconds is not None
        and audio_duration_seconds > max_seconds
    ):
        raise TranscriptionGuardError(
            "recording_too_long",
            "Recording exceeds the maximum supported length for transcription.",
        )
    await check_minutes_budget(guard_user_id, estimated_minutes)

    started_at = perf_counter()
    audio_bytes = len(audio_data)
    start_data = {
        "provider": provider,
        "model": selected_model,
        "audio_bytes": audio_bytes,
        "content_type": content_type,
        "channels": channels,
        "audio_duration_seconds": audio_duration_seconds,
    }
    if usage_purpose is not None:
        start_data["usage_purpose"] = usage_purpose
    add_sentry_breadcrumb(
        category="recording",
        message="File transcription started",
        data=start_data,
    )

    try:
        if provider == "elevenlabs":
            results = await elevenlabs_transcribe_audio_file(
                audio_data,
                language=language,
                content_type=content_type,
                model=selected_model,
                keyterms=keyterms,
                replacements=replacements,
                audio_duration_seconds=audio_duration_seconds,
            )
        else:
            results = await deepgram_transcribe_audio_file(
                audio_data,
                language=language,
                content_type=content_type,
                channels=channels,
                model=selected_model,
                keyterms=keyterms,
                replacements=replacements,
                max_channels=settings.deepgram_max_channels,
                audio_duration_seconds=audio_duration_seconds,
            )
    except httpx.HTTPStatusError as exc:
        await record_provider_result(success=False, status_code=exc.response.status_code)
        error_code = _provider_error_code(exc) or "unknown"
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
        await record_provider_result(success=False)
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

    await record_provider_result(success=True)
    await record_minutes(guard_user_id, estimated_minutes)
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
    if usage_purpose is not None:
        completion_data["usage_purpose"] = usage_purpose
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
