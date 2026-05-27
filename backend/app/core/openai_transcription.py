"""OpenAI speech-to-text helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult

OPENAI_API_BASE = "https://api.openai.com"
OPENAI_REALTIME_WS_URL = "wss://api.openai.com/v1/realtime"
OPENAI_REALTIME_SAMPLE_RATE = 24_000
OPENAI_REALTIME_TOKEN_TTL_SECONDS = 15 * 60
OPENAI_MAX_TRANSCRIPTION_FILE_BYTES = 24 * 1024 * 1024
OPENAI_TRANSCODE_CHUNK_MS = 60 * 60 * 1000
OPENAI_TRANSCODE_BITRATE = "24k"
OPENAI_FILE_STT_FILENAME_EXTENSIONS = {
    "audio/flac": "flac",
    "audio/m4a": "m4a",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/mpga": "mpga",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/webm": "webm",
    "audio/x-m4a": "m4a",
    "audio/x-wav": "wav",
    "video/mp4": "mp4",
    "video/webm": "webm",
}
TRANSCODABLE_CONTENT_TYPES = OPENAI_FILE_STT_FILENAME_EXTENSIONS | {
    "audio/aac": "aac",
    "audio/opus": "opus",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
}


@dataclass(frozen=True)
class OpenAIFileSTTUpload:
    data: bytes
    content_type: str
    filename: str
    offset_ms: int


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    return settings.openai_api_key


def build_realtime_transcription_session_update(
    *,
    model: str,
    language: str,
    turn_detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the OpenAI realtime transcription session update payload."""
    transcription: dict[str, Any] = {"model": model}
    if language and language != "multi":
        transcription["language"] = language

    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": OPENAI_REALTIME_SAMPLE_RATE,
                    },
                    "transcription": transcription,
                    "turn_detection": turn_detection,
                }
            },
        },
    }


async def create_realtime_client_secret(*, model: str, language: str) -> str:
    """Create an ephemeral client secret for OpenAI Realtime transcription."""
    api_key = _require_api_key()
    session_update = build_realtime_transcription_session_update(
        model=model,
        language=language,
        turn_detection=None,
    )
    payload = {"session": session_update["session"]}

    async with httpx.AsyncClient(base_url=OPENAI_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    value = None
    if isinstance(body, dict):
        client_secret = body.get("client_secret")
        if isinstance(client_secret, dict):
            value = client_secret.get("value")
        if value is None:
            value = body.get("value") or body.get("secret")

    if not isinstance(value, str) or not value:
        raise RuntimeError("OpenAI returned an invalid realtime client secret")
    return value


def realtime_websocket_url(model: str) -> str:
    return f"{OPENAI_REALTIME_WS_URL}?model={model}"


def _file_stt_upload_filename(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    extension = OPENAI_FILE_STT_FILENAME_EXTENSIONS.get(normalized)
    if not extension:
        raise ValueError(f"Unsupported OpenAI STT content type: {content_type}")
    return f"recording.{extension}"


def _file_stt_language_code(language: str | None) -> str | None:
    normalized = (language or "").strip().lower().replace("_", "-")
    if not normalized or normalized in {"auto", "multi", "und"}:
        return None
    return normalized.split("-", 1)[0]


def _segment_time_ms(segment: dict[str, Any], key: str) -> int:
    value = segment.get(key, 0)
    if not isinstance(value, (float, int)):
        raise RuntimeError(f"OpenAI STT returned invalid segment {key}")
    return int(float(value) * 1000)


def _segment_text(segment: dict[str, Any]) -> str:
    text = segment.get("text")
    if not isinstance(text, str):
        raise RuntimeError("OpenAI STT returned invalid segment text")
    return text.strip()


def _segment_speaker(segment: dict[str, Any]) -> str | None:
    speaker = segment.get("speaker")
    if speaker is None:
        return None
    if not isinstance(speaker, str):
        raise RuntimeError("OpenAI STT returned invalid segment speaker")
    return speaker or None


def _results_from_diarized_payload(payload: Any) -> list[TranscriptResult]:
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"OpenAI STT returned unexpected payload type={type(payload).__name__}"
        )

    segments = payload.get("segments")
    if not isinstance(segments, list):
        text = payload.get("text")
        if isinstance(text, str) and not text.strip():
            return []
        raise RuntimeError("OpenAI STT returned invalid diarized transcription payload")

    results: list[TranscriptResult] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise RuntimeError(f"OpenAI STT returned invalid segment entry at index {index}")
        text = _segment_text(segment)
        if not text:
            continue
        results.append(
            TranscriptResult(
                text=text,
                speaker=_segment_speaker(segment),
                is_final=True,
                start_ms=_segment_time_ms(segment, "start"),
                end_ms=_segment_time_ms(segment, "end"),
                confidence=0.0,
            )
        )
    return results


def _with_offset(results: list[TranscriptResult], offset_ms: int) -> list[TranscriptResult]:
    if offset_ms == 0:
        return results
    return [
        TranscriptResult(
            text=result.text,
            speaker=result.speaker,
            is_final=result.is_final,
            start_ms=result.start_ms + offset_ms,
            end_ms=result.end_ms + offset_ms,
            confidence=result.confidence,
        )
        for result in results
    ]


def _pydub_format(content_type: str) -> str | None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized == "audio/wave":
        return "wav"
    extension = TRANSCODABLE_CONTENT_TYPES.get(normalized)
    if extension == "mov":
        return None
    return extension


def _transcoded_uploads(audio_data: bytes, content_type: str) -> list[OpenAIFileSTTUpload]:
    from pydub import AudioSegment

    segment = AudioSegment.from_file(BytesIO(audio_data), format=_pydub_format(content_type))
    segment = segment.set_frame_rate(16_000).set_channels(1)

    uploads: list[OpenAIFileSTTUpload] = []
    for start_ms in range(0, len(segment), OPENAI_TRANSCODE_CHUNK_MS):
        chunk = segment[start_ms:start_ms + OPENAI_TRANSCODE_CHUNK_MS]
        output = BytesIO()
        chunk.export(output, format="mp3", bitrate=OPENAI_TRANSCODE_BITRATE)
        chunk_data = output.getvalue()
        if len(chunk_data) > OPENAI_MAX_TRANSCRIPTION_FILE_BYTES:
            raise RuntimeError("OpenAI STT transcode chunk exceeded upload size limit")
        uploads.append(
            OpenAIFileSTTUpload(
                data=chunk_data,
                content_type="audio/mpeg",
                filename=f"recording-{len(uploads) + 1}.mp3",
                offset_ms=start_ms,
            )
        )
    return uploads


async def _prepare_file_stt_uploads(
    audio_data: bytes,
    *,
    content_type: str,
) -> list[OpenAIFileSTTUpload]:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in TRANSCODABLE_CONTENT_TYPES:
        raise ValueError(f"Unsupported OpenAI STT content type: {content_type}")
    if (
        len(audio_data) <= OPENAI_MAX_TRANSCRIPTION_FILE_BYTES
        and normalized in OPENAI_FILE_STT_FILENAME_EXTENSIONS
    ):
        return [
            OpenAIFileSTTUpload(
                data=audio_data,
                content_type=content_type,
                filename=_file_stt_upload_filename(content_type),
                offset_ms=0,
            )
        ]
    return await asyncio.to_thread(_transcoded_uploads, audio_data, content_type)


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
    model: str,
) -> list[TranscriptResult]:
    """Transcribe an audio file with OpenAI's diarized transcription API."""
    del channels
    api_key = _require_api_key()
    form_data: dict[str, Any] = {
        "model": model,
        "response_format": "diarized_json",
        "chunking_strategy": "auto",
    }
    language_code = _file_stt_language_code(language)
    if language_code:
        form_data["language"] = language_code

    uploads = await _prepare_file_stt_uploads(audio_data, content_type=content_type)
    results: list[TranscriptResult] = []

    async with httpx.AsyncClient(base_url=OPENAI_API_BASE, timeout=300.0) as client:
        for upload in uploads:
            response = await client.post(
                "/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data=form_data,
                files={
                    "file": (upload.filename, upload.data, upload.content_type),
                },
            )
            response.raise_for_status()
            chunk_results = _results_from_diarized_payload(response.json())
            results.extend(_with_offset(chunk_results, upload.offset_ms))

    return results
