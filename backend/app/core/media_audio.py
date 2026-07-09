"""File-based ffmpeg audio extraction shared by every media import path.

Any container ffmpeg can demux — video (mp4/mov/mkv/webm/avi/…) or audio that
STT providers reject — is reduced to a compact 16 kHz mono FLAC on disk before
transcription. Everything is file→file so memory stays flat regardless of the
source size: the previous pydub approach decoded the full source into RAM and
OOM-killed the API container on large videos (236 MB Telegram mp4, 2026-07-09).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ffmpeg demuxes + resamples far faster than realtime; even multi-hour sources
# finish in minutes. The timeout only exists to kill a truly wedged process.
AUDIO_EXTRACT_TIMEOUT_SECONDS = 1800
MEDIA_DURATION_PROBE_TIMEOUT_SECONDS = 60

# Deepgram file STT accepts FLAC natively; 16 kHz mono FLAC is lossless for
# speech models (~30 MB/hour vs ~115 MB/hour WAV) and pydub/speechbrain can
# read it for voice identification.
EXTRACTED_AUDIO_EXT = "flac"
EXTRACTED_AUDIO_CONTENT_TYPE = "audio/flac"

# Single source of truth for importable media types across every surface
# (native uploads, web materials, Telegram). Audio formats STT providers accept
# directly pass through untouched; everything else goes through ffmpeg.
CONTENT_TYPE_TO_EXTENSION = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/oga": "oga",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/x-ms-wma": "wma",
    "audio/amr": "amr",
    "audio/amr-wb": "amr",
    "audio/x-matroska": "mka",
    "audio/x-caf": "caf",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "video/avi": "avi",
    "video/mpeg": "mpg",
    "video/x-m4v": "m4v",
    "video/x-ms-wmv": "wmv",
    "video/x-flv": "flv",
    "video/3gpp": "3gp",
    "video/3gpp2": "3g2",
    "video/mp2t": "ts",
}
EXTENSION_TO_CONTENT_TYPE = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/opus",
    "webm": "audio/webm",
    "flac": "audio/flac",
    "aiff": "audio/aiff",
    "aif": "audio/aiff",
    "wma": "audio/x-ms-wma",
    "amr": "audio/amr",
    "mka": "audio/x-matroska",
    "caf": "audio/x-caf",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "m4v": "video/x-m4v",
    "mpg": "video/mpeg",
    "mpeg": "video/mpeg",
    "wmv": "video/x-ms-wmv",
    "flv": "video/x-flv",
    "3gp": "video/3gpp",
    "3g2": "video/3gpp2",
    "ts": "video/mp2t",
    "mts": "video/mp2t",
}
SUPPORTED_AUDIO_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "aac",
    "ogg",
    "oga",
    "opus",
    "webm",
    "flac",
    "aiff",
    "aif",
    "wma",
    "amr",
    "mka",
    "caf",
}
SUPPORTED_VIDEO_EXTENSIONS = {
    "mp4",
    "mov",
    "m4v",
    "webm",
    "mkv",
    "avi",
    "mpg",
    "mpeg",
    "wmv",
    "flv",
    "3gp",
    "3g2",
    "ts",
    "mts",
}
# Containers STT providers reject or handle unreliably; ffmpeg re-encodes them
# to FLAC alongside the video extractions.
AUDIO_EXTENSIONS_REQUIRING_NORMALIZATION = {
    "ogg",
    "oga",
    "opus",
    "webm",
    "aiff",
    "aif",
    "wma",
    "amr",
    "mka",
    "caf",
}
_AUDIO_CONTENT_TYPES_REQUIRING_NORMALIZATION = {
    "audio/ogg",
    "audio/oga",
    "audio/opus",
    "audio/webm",
    "audio/aiff",
    "audio/x-aiff",
    "audio/x-ms-wma",
    "audio/amr",
    "audio/amr-wb",
    "audio/x-matroska",
    "audio/x-caf",
}


def normalized_media_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def is_video_media(ext: str, content_type: str | None) -> bool:
    normalized = normalized_media_content_type(content_type)
    if normalized.startswith("video/"):
        return True
    if normalized.startswith("audio/"):
        return False
    return ext in SUPPORTED_VIDEO_EXTENSIONS


def is_audio_media_requiring_normalization(ext: str, content_type: str | None) -> bool:
    if ext in AUDIO_EXTENSIONS_REQUIRING_NORMALIZATION:
        return True
    return (
        normalized_media_content_type(content_type)
        in _AUDIO_CONTENT_TYPES_REQUIRING_NORMALIZATION
    )


def media_requires_audio_extraction(ext: str, content_type: str | None) -> bool:
    """True when this media must be reduced to FLAC before STT (video or an
    audio container providers reject)."""
    return is_video_media(ext, content_type) or is_audio_media_requiring_normalization(
        ext, content_type
    )

_NO_AUDIO_STREAM_MARKERS = (
    "matches no streams",
    "does not contain any stream",
    "output file does not contain any stream",
)


class MediaAudioExtractionError(Exception):
    """ffmpeg could not produce an audio track from the source media."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _extract_audio_to_flac_sync(source: Path, dest: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "flac",
        str(dest),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=AUDIO_EXTRACT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        dest.unlink(missing_ok=True)
        raise MediaAudioExtractionError(
            "audio_extract_timeout",
            "Не получилось извлечь звук: обработка заняла слишком много времени.",
        ) from exc
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise MediaAudioExtractionError(
            "audio_extract_failed",
            "Не получилось извлечь звук из файла.",
        ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        dest.unlink(missing_ok=True)
        # Privacy-safe: ffmpeg stderr contains the file path but never user
        # content; log only the tail for diagnosis.
        logger.warning(
            "ffmpeg audio extraction failed rc=%s stderr_tail=%s",
            completed.returncode,
            stderr[-500:],
        )
        lowered = stderr.lower()
        if any(marker in lowered for marker in _NO_AUDIO_STREAM_MARKERS):
            raise MediaAudioExtractionError(
                "no_audio_stream",
                "В этом файле нет звуковой дорожки — расшифровывать нечего.",
            )
        raise MediaAudioExtractionError(
            "audio_extract_failed",
            "Не получилось извлечь звук из файла.",
        )
    if not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise MediaAudioExtractionError(
            "audio_extract_failed",
            "Не получилось извлечь звук из файла.",
        )


async def extract_audio_to_flac(source: Path, dest: Path) -> Path:
    """Extract the first audio stream of ``source`` into a 16 kHz mono FLAC.

    Raises :class:`MediaAudioExtractionError` (``no_audio_stream`` /
    ``audio_extract_failed`` / ``audio_extract_timeout``) — messages are
    user-facing Russian, matching the import error convention.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_extract_audio_to_flac_sync, source, dest)
    return dest


def probe_media_duration_seconds_sync(path: Path) -> float | None:
    """Container-level duration via ffprobe; None when it cannot be determined.

    Feeds the transcription guards and billing estimates, so a probe failure is
    survivable (the transcript end timestamp still backfills the recording
    duration) but should stay rare.
    """
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=MEDIA_DURATION_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("ffprobe media duration probe failed to run")
        return None
    if completed.returncode != 0:
        logger.warning(
            "ffprobe media duration probe failed rc=%s", completed.returncode
        )
        return None
    lines = completed.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        duration = float(lines[0])
    except ValueError:
        return None
    if duration <= 0:
        return None
    return duration


async def probe_media_duration_seconds(path: Path) -> float | None:
    return await asyncio.to_thread(probe_media_duration_seconds_sync, path)
