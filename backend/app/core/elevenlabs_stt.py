"""ElevenLabs Scribe pre-recorded (batch) speech-to-text.

Scribe returns word-level results (``words[]`` with per-word timestamps and
``speaker_id``); this module assembles them into the utterance-shaped
``TranscriptResult`` segments the rest of the stack consumes (persisted
segments, speaker identification, summaries, search embeddings).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import BinaryIO

import httpx

from app.config import get_settings
from app.core.transcript_utils import (
    FileTranscription,
    TranscriptResult,
    TranscriptWord,
)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_BATCH_MODEL = "scribe_v2"

# Scribe accepts up to 1000 keyterms (<=50 chars each). Keep a conservative cap:
# the dictionary-learning pipeline rarely produces more, and a runaway keyterm
# list past 100 terms triggers ElevenLabs' minimum-billing surcharge.
ELEVENLABS_MAX_KEYTERMS = 100
ELEVENLABS_MAX_KEYTERM_CHARS = 50

# Utterance assembly over the word stream. A segment closes on a speaker
# change, a silence gap, a sentence boundary once the segment is long enough,
# or a hard duration cap (protects search-embedding quality on monologues).
SEGMENT_GAP_SECONDS = 1.2
SEGMENT_SOFT_DURATION_SECONDS = 12.0
SEGMENT_HARD_DURATION_SECONDS = 40.0

ELEVENLABS_BATCH_TIMEOUT_SECONDS = 300.0
# Scribe batch latency scales with audio length; allow generous headroom so a
# multi-hour file doesn't fail on read timeout after minutes of upload.
ELEVENLABS_BATCH_READ_TIMEOUT_SECONDS_PER_AUDIO_MINUTE = 10.0

_SENTENCE_END_RE = re.compile(r"[.!?…]['\")»”]?$")


def require_elevenlabs_api_key() -> str:
    api_key = get_settings().elevenlabs_api_key
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    return api_key


def resolve_scribe_language_code(language: str | None) -> str | None:
    """Map the app's language setting to a Scribe ``language_code``.

    ``auto``/``multi``/empty mean "let Scribe detect"; otherwise pass the bare
    ISO-639 base subtag (``ru-RU`` -> ``ru``). Unrecognizable values fall back
    to detection rather than failing the transcription on a preference field.
    """
    normalized = (language or "").strip().lower()
    if normalized in {"", "auto", "multi"}:
        return None
    base = normalized.split("-", 1)[0]
    if 2 <= len(base) <= 3 and base.isalpha():
        return base
    return None


def sanitize_scribe_keyterms(keyterms: list[str] | None) -> list[str]:
    """Dedupe/trim keyterms to Scribe's per-term constraints."""
    if not keyterms:
        return []
    sanitized: list[str] = []
    seen: set[str] = set()
    for term in keyterms:
        cleaned = " ".join(str(term).split())
        if not cleaned or len(cleaned) > ELEVENLABS_MAX_KEYTERM_CHARS:
            continue
        if len(cleaned.split()) > 5:
            continue
        marker = cleaned.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        sanitized.append(cleaned)
        if len(sanitized) >= ELEVENLABS_MAX_KEYTERMS:
            break
    return sanitized


def apply_transcript_replacements(
    text: str,
    replacements: list[tuple[str, str]] | None,
) -> str:
    """Apply the user's find->replace dictionary to a transcript segment.

    Deepgram applied these natively (``replace=find:replacement``); Scribe has
    no equivalent, so the same pairs are applied post-transcription. Matching is
    case-insensitive on word boundaries, mirroring how the pairs behaved as
    recognition hints.
    """
    if not replacements:
        return text
    result = text
    for find, replacement in replacements:
        find = str(find).strip()
        if not find:
            continue
        pattern = re.compile(
            rf"(?<![\w]){re.escape(find)}(?![\w])",
            re.IGNORECASE | re.UNICODE,
        )
        result = pattern.sub(replacement, result)
    return result


def _word_confidence(word: dict) -> float | None:
    logprob = word.get("logprob")
    if isinstance(logprob, (int, float)) and not isinstance(logprob, bool):
        return max(0.0, min(1.0, math.exp(float(logprob))))
    return None


class _SegmentBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.speaker: str | None = None
        self.start_s: float | None = None
        self.end_s: float = 0.0
        self.confidences: list[float] = []

    def empty(self) -> bool:
        return not "".join(self.parts).strip()

    def add_word(self, word: dict, *, start: float, end: float) -> None:
        if self.start_s is None:
            self.start_s = start
        self.end_s = max(self.end_s, end)
        self.parts.append(str(word.get("text") or ""))
        confidence = _word_confidence(word)
        if confidence is not None:
            self.confidences.append(confidence)

    def add_spacing(self, word: dict) -> None:
        if self.parts:
            self.parts.append(str(word.get("text") or ""))

    def build(self, replacements: list[tuple[str, str]] | None) -> TranscriptResult | None:
        text = "".join(self.parts).strip()
        if not text:
            return None
        text = apply_transcript_replacements(text, replacements)
        confidence = (
            sum(self.confidences) / len(self.confidences) if self.confidences else 1.0
        )
        return TranscriptResult(
            text=text,
            speaker=self.speaker,
            is_final=True,
            start_ms=int(round((self.start_s or 0.0) * 1000)),
            end_ms=int(round(self.end_s * 1000)),
            confidence=round(confidence, 4),
        )


def _results_from_scribe_payload(
    payload: object,
    *,
    replacements: list[tuple[str, str]] | None = None,
) -> FileTranscription:
    """Assemble Scribe word-level output into utterance-shaped segments.

    The returned ``words`` keep the provider's raw text (no find/replace
    applied) — they exist for timing/alignment passes, not display.
    """
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"ElevenLabs STT returned unexpected payload type={type(payload).__name__}"
        )
    words = payload.get("words")
    if not isinstance(words, list):
        raise RuntimeError("ElevenLabs STT response missing words array")

    results: list[TranscriptResult] = []
    transcript_words: list[TranscriptWord] = []
    current = _SegmentBuilder()

    def close_current() -> None:
        nonlocal current
        built = current.build(replacements)
        if built is not None:
            results.append(built)
        current = _SegmentBuilder()

    for word in words:
        if not isinstance(word, dict):
            raise RuntimeError("ElevenLabs STT returned an invalid word entry")
        word_type = str(word.get("type") or "word")
        if word_type == "spacing":
            current.add_spacing(word)
            continue
        if word_type == "audio_event":
            continue

        start = float(word.get("start") or 0.0)
        end = float(word.get("end") or start)
        raw_speaker = word.get("speaker_id")
        speaker = str(raw_speaker) if raw_speaker not in (None, "") else None

        if not current.empty():
            gap = start - current.end_s
            duration = current.end_s - (current.start_s or 0.0)
            text_so_far = "".join(current.parts).rstrip()
            sentence_done = bool(_SENTENCE_END_RE.search(text_so_far))
            if (
                speaker != current.speaker
                or gap > SEGMENT_GAP_SECONDS
                or duration >= SEGMENT_HARD_DURATION_SECONDS
                or (duration >= SEGMENT_SOFT_DURATION_SECONDS and sentence_done)
            ):
                close_current()

        if current.empty():
            current.speaker = speaker
        current.add_word(word, start=start, end=end)
        word_text = str(word.get("text") or "").strip()
        if word_text:
            transcript_words.append(
                TranscriptWord(
                    text=word_text,
                    speaker=speaker,
                    start_ms=int(round(start * 1000)),
                    end_ms=int(round(end * 1000)),
                    confidence=_word_confidence(word),
                )
            )

    close_current()

    detected_language = payload.get("language_code")
    language_probability = payload.get("language_probability")
    return FileTranscription(
        segments=results,
        words=transcript_words,
        detected_language=(
            str(detected_language) if isinstance(detected_language, str) else None
        ),
        language_probability=(
            float(language_probability)
            if isinstance(language_probability, (int, float))
            and not isinstance(language_probability, bool)
            else None
        ),
    )


def _batch_timeout(audio_duration_seconds: float | None) -> httpx.Timeout:
    read_timeout = ELEVENLABS_BATCH_TIMEOUT_SECONDS
    if audio_duration_seconds is not None and audio_duration_seconds > 0:
        audio_minutes = audio_duration_seconds / 60.0
        read_timeout = max(
            ELEVENLABS_BATCH_TIMEOUT_SECONDS,
            audio_minutes * ELEVENLABS_BATCH_READ_TIMEOUT_SECONDS_PER_AUDIO_MINUTE,
        )
    return httpx.Timeout(connect=10.0, read=read_timeout, write=600.0, pool=10.0)


def _upload_filename(content_type: str) -> str:
    subtype = (content_type or "").split(";", 1)[0].split("/", 1)[-1].strip().lower()
    extension = {
        "mpeg": "mp3",
        "mp4": "mp4",
        "x-m4a": "m4a",
        "aac": "m4a",
        "ogg": "ogg",
        "opus": "opus",
        "webm": "webm",
        "wav": "wav",
        "x-wav": "wav",
        "flac": "flac",
        "raw": "raw",
    }.get(subtype, subtype or "bin")
    return f"audio.{extension}"


async def transcribe_audio_file(
    audio_data: bytes | Path,
    *,
    language: str = "auto",
    content_type: str = "audio/wav",
    model: str | None = None,
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
    audio_duration_seconds: float | None = None,
) -> FileTranscription:
    """Transcribe an uploaded audio file with ElevenLabs Scribe.

    ``Path`` payloads are handed to httpx as file objects, which it streams
    into the multipart body without buffering the whole file in memory."""
    api_key = require_elevenlabs_api_key()
    settings = get_settings()

    fields: dict[str, str | list[str]] = {
        "model_id": model or ELEVENLABS_BATCH_MODEL,
        "diarize": "true",
        "tag_audio_events": "false",
        "timestamps_granularity": "word",
    }
    if settings.elevenlabs_stt_no_verbatim:
        fields["no_verbatim"] = "true"
    language_code = resolve_scribe_language_code(language)
    if language_code is not None:
        fields["language_code"] = language_code
    sanitized_keyterms = sanitize_scribe_keyterms(keyterms)
    if sanitized_keyterms:
        fields["keyterms"] = sanitized_keyterms

    file_handle = audio_data.open("rb") if isinstance(audio_data, Path) else None
    try:
        upload_payload: bytes | BinaryIO = (
            file_handle if file_handle is not None else audio_data  # type: ignore[assignment]
        )
        async with httpx.AsyncClient(
            timeout=_batch_timeout(audio_duration_seconds)
        ) as client:
            response = await client.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": api_key},
                data=fields,
                files={
                    "file": (
                        _upload_filename(content_type),
                        upload_payload,
                        content_type,
                    )
                },
            )
            response.raise_for_status()
            payload = response.json()
    finally:
        if file_handle is not None:
            file_handle.close()

    return _results_from_scribe_payload(payload, replacements=replacements)
