"""Deepgram realtime speech-to-text helpers."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.personalization import sanitize_keyterms
from app.core.transcript_utils import TranscriptResult, detect_wav_channels

DEEPGRAM_REALTIME_WS_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_REALTIME_MODEL = "nova-3"
DEEPGRAM_REALTIME_SAMPLE_RATE = 16_000
DEEPGRAM_REALTIME_CHANNELS = 1
DEEPGRAM_REALTIME_ENCODING = "linear16"
DEEPGRAM_KEEP_ALIVE_INTERVAL_SECONDS = 4
DEEPGRAM_UTTERANCE_END_MS = 1_000
# Silence (ms) before Deepgram finalizes a streaming segment (is_final=true).
# Meeting recording keeps a slightly longer value so spoken number sequences
# stay together for formatting. Dictation optimizes for commit latency.
DEEPGRAM_RECORDING_ENDPOINTING_MS = 300
# Deepgram recommends 10 ms endpointing for short chatbot-style utterances.
# Dictation can safely emit smaller final segments; commit latency matters more.
DEEPGRAM_DICTATION_ENDPOINTING_MS = 10
DEEPGRAM_ENDPOINTING_MS = DEEPGRAM_RECORDING_ENDPOINTING_MS
DEEPGRAM_MAX_KEYTERMS = 100
DEEPGRAM_MAX_KEYTERM_CHARS = 100
DEEPGRAM_KEYTERM_TOKEN_BUDGET = 500

_NUMERALS_LANGUAGES = {
    "da",
    "da-dk",
    "nl",
    "en",
    "en-us",
    "en-au",
    "en-gb",
    "en-nz",
    "en-in",
    "fr",
    "fr-ca",
    "de",
    "de-ch",
    "it",
    "no",
    "pl",
    "pt",
    "pt-br",
    "pt-pt",
    "es",
    "es-419",
    "sv",
    "sv-se",
    "ru",
    "he",
    "ro",
}

_SUPPORTED_NOVA3_LANGUAGES = {
    "ar",
    "ar-ae",
    "ar-sa",
    "ar-qa",
    "ar-kw",
    "ar-sy",
    "ar-lb",
    "ar-ps",
    "ar-jo",
    "ar-eg",
    "ar-sd",
    "ar-td",
    "ar-ma",
    "ar-dz",
    "ar-tn",
    "ar-iq",
    "ar-ir",
    "be",
    "bn",
    "bs",
    "bg",
    "ca",
    "hr",
    "cs",
    "da",
    "da-dk",
    "nl",
    "nl-be",
    "en",
    "en-us",
    "en-au",
    "en-gb",
    "en-in",
    "en-nz",
    "et",
    "fi",
    "fr",
    "fr-ca",
    "de",
    "de-ch",
    "el",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "kn",
    "ko",
    "ko-kr",
    "lv",
    "lt",
    "mk",
    "ms",
    "mr",
    "no",
    "fa",
    "pl",
    "pt",
    "pt-br",
    "pt-pt",
    "ro",
    "ru",
    "sr",
    "sk",
    "sl",
    "es",
    "es-419",
    "sv",
    "sv-se",
    "tl",
    "ta",
    "te",
    "tr",
    "uk",
    "ur",
    "vi",
}


def require_deepgram_api_key() -> str:
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")
    return settings.deepgram_api_key


def normalize_deepgram_language(language: str | None) -> str:
    normalized = (language or "").strip().lower().replace("_", "-")
    if normalized in {"", "auto", "und", "multi"}:
        return "multi"
    if normalized in _SUPPORTED_NOVA3_LANGUAGES:
        return normalized
    base_language = normalized.split("-", 1)[0]
    if base_language in _SUPPORTED_NOVA3_LANGUAGES:
        return base_language
    return normalized


def validate_deepgram_language(language: str | None) -> str:
    normalized = normalize_deepgram_language(language)
    if normalized == "multi" or normalized in _SUPPORTED_NOVA3_LANGUAGES:
        return normalized
    raise ValueError(f"Unsupported Deepgram language: {normalized}")


def supports_numerals(language: str) -> bool:
    return language == "multi" or language in _NUMERALS_LANGUAGES


def supports_dictation(language: str) -> bool:
    return language == "en" or language.startswith("en-")


DEEPGRAM_MAX_REPLACEMENTS = 200


def sanitize_deepgram_keyterms(keyterms: list[str] | None) -> list[str]:
    if not keyterms:
        return []
    return sanitize_keyterms(
        keyterms,
        max_terms=DEEPGRAM_MAX_KEYTERMS,
        max_chars=DEEPGRAM_MAX_KEYTERM_CHARS,
        max_words=8,
        token_budget=DEEPGRAM_KEYTERM_TOKEN_BUDGET,
    )


def sanitize_deepgram_replacements(
    replacements: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    """Normalize find/replace pairs for Deepgram's find-and-replace.

    Deepgram matches the FIND term case-insensitively but requires it supplied
    lowercase, so we lowercase it here. A pair that would replace a word with
    itself (case-insensitively) is dropped — it can only cost tokens and risk a
    no-op rewrite. De-duped by find and capped to keep the URL bounded.
    """
    if not replacements:
        return []
    sanitized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for find, replace in replacements:
        find_clean = find.strip().lower()
        replace_clean = replace.strip()
        if not find_clean or find_clean in seen:
            continue
        if find_clean.casefold() == replace_clean.casefold():
            continue
        seen.add(find_clean)
        sanitized.append((find_clean, replace_clean))
        if len(sanitized) >= DEEPGRAM_MAX_REPLACEMENTS:
            break
    return sanitized


def build_realtime_websocket_url(
    *,
    language: str,
    channels: int,
    purpose: Literal["recording", "dictation"],
    model: str = DEEPGRAM_REALTIME_MODEL,
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    resolved_language = normalize_deepgram_language(language)
    endpointing_ms = (
        DEEPGRAM_DICTATION_ENDPOINTING_MS
        if purpose == "dictation"
        else DEEPGRAM_RECORDING_ENDPOINTING_MS
    )
    params: list[tuple[str, str | int]] = [
        ("model", model),
        ("encoding", DEEPGRAM_REALTIME_ENCODING),
        ("sample_rate", DEEPGRAM_REALTIME_SAMPLE_RATE),
        ("channels", max(1, channels)),
        ("language", resolved_language),
        ("interim_results", "true"),
        ("vad_events", "true"),
        ("utterance_end_ms", DEEPGRAM_UTTERANCE_END_MS),
        ("endpointing", endpointing_ms),
    ]
    if purpose == "recording":
        # smart_format optimizes meeting transcripts for human readability
        # (punctuation, paragraphs, dates/times). Its readability layer keeps
        # small spoken numbers as words ("десять") — desirable for meetings.
        params.append(("smart_format", "true"))
        params.append(("utterances", "true"))
        params.append(("diarize", "true"))
    if purpose == "dictation":
        # Dictation wants EVERY spoken number as a digit (десять -> 10). numerals
        # (added below) does that, but ONLY without smart_format: smart_format's
        # readability layer overrides numerals and leaves small numbers as words.
        # punctuate gives sentence stops without smart_format's paragraph reflow.
        params.append(("punctuate", "true"))
        if supports_dictation(resolved_language):
            # English-only: turn spoken punctuation commands into marks.
            params.append(("dictation", "true"))
    if supports_numerals(resolved_language):
        params.append(("numerals", "true"))
    params.extend(("keyterm", keyterm) for keyterm in sanitize_deepgram_keyterms(keyterms))
    params.extend(
        ("replace", f"{find}:{replace}")
        for find, replace in sanitize_deepgram_replacements(replacements)
    )
    return f"{DEEPGRAM_REALTIME_WS_URL}?{urlencode(params)}"


# --- Batch (pre-recorded) file transcription -------------------------------

DEEPGRAM_BATCH_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_BATCH_MODEL = "nova-3"
# diarize_model=latest selects the v2 batch diarizer. It is batch-only and must
# NOT be combined with diarize=true (Deepgram rejects that pairing with HTTP 400).
DEEPGRAM_BATCH_DIARIZE_MODEL = "latest"
DEEPGRAM_BATCH_TIMEOUT_SECONDS = 300.0
DEEPGRAM_BATCH_READ_TIMEOUT_SECONDS_PER_AUDIO_MINUTE = 10.0
# Deepgram auto-detects container formats from the audio bytes, but we send a
# canonical Content-Type so non-standard aliases (e.g. audio/x-m4a from web
# uploads) never reach the API. Raw PCM (audio/raw) is intentionally not aliased.
DEEPGRAM_CONTENT_TYPE_ALIASES = {
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
}


def build_batch_url(
    *,
    language: str,
    multichannel: bool,
    raw_pcm: bool = False,
    channels: int = DEEPGRAM_REALTIME_CHANNELS,
    model: str = DEEPGRAM_BATCH_MODEL,
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Build the Deepgram pre-recorded transcription URL for file STT."""
    resolved_language = normalize_deepgram_language(language)
    params: list[tuple[str, str | int]] = [
        ("model", model),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("paragraphs", "true"),
        ("utterances", "true"),
        ("language", resolved_language),
    ]
    if raw_pcm:
        # Raw/headerless PCM needs explicit encoding hints; containerized audio
        # is auto-detected by Deepgram, so these are omitted for it.
        params.extend(
            (
                ("encoding", DEEPGRAM_REALTIME_ENCODING),
                ("sample_rate", DEEPGRAM_REALTIME_SAMPLE_RATE),
                ("channels", max(1, channels)),
            )
        )
    if multichannel:
        params.append(("multichannel", "true"))
    else:
        params.append(("diarize_model", DEEPGRAM_BATCH_DIARIZE_MODEL))
    if supports_numerals(resolved_language):
        params.append(("numerals", "true"))
    params.extend(("keyterm", keyterm) for keyterm in sanitize_deepgram_keyterms(keyterms))
    params.extend(
        ("replace", f"{find}:{replace}")
        for find, replace in sanitize_deepgram_replacements(replacements)
    )
    return f"{DEEPGRAM_BATCH_URL}?{urlencode(params)}"


def _results_from_deepgram_payload(payload: object) -> list[TranscriptResult]:
    """Map a Deepgram pre-recorded response into normalized transcript segments."""
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Deepgram STT returned unexpected payload type={type(payload).__name__}"
        )
    results_obj = payload.get("results")
    if not isinstance(results_obj, dict):
        raise RuntimeError("Deepgram STT response missing results object")
    utterances = results_obj.get("utterances")
    if not isinstance(utterances, list):
        raise RuntimeError(
            "Deepgram STT response missing utterances; ensure utterances=true"
        )

    results: list[TranscriptResult] = []
    for utterance in utterances:
        if not isinstance(utterance, dict):
            raise RuntimeError("Deepgram STT returned an invalid utterance entry")
        text = str(utterance.get("transcript", "")).strip()
        if not text:
            continue
        # Emit the canonical raw diarization label (``speaker_0``) that the rest
        # of the stack expects (see app/core/speaker_labels.py and the web
        # formatter); this matches the format the previous provider produced, so
        # persisted segments and speaker-name extraction stay format-stable.
        speaker = _speaker_label_from_utterance(utterance)
        results.append(
            TranscriptResult(
                text=text,
                speaker=speaker,
                is_final=True,
                start_ms=int(float(utterance.get("start", 0.0)) * 1000),
                end_ms=int(float(utterance.get("end", 0.0)) * 1000),
                confidence=float(utterance.get("confidence", 0.0)),
            )
        )
    return results


def _batch_timeout(audio_duration_seconds: float | None) -> httpx.Timeout:
    read_timeout = DEEPGRAM_BATCH_TIMEOUT_SECONDS
    if audio_duration_seconds is not None and audio_duration_seconds > 0:
        audio_minutes = audio_duration_seconds / 60.0
        read_timeout = max(
            DEEPGRAM_BATCH_TIMEOUT_SECONDS,
            audio_minutes * DEEPGRAM_BATCH_READ_TIMEOUT_SECONDS_PER_AUDIO_MINUTE,
        )
    return httpx.Timeout(
        connect=10.0,
        read=read_timeout,
        write=60.0,
        pool=10.0,
    )


def _integer_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _speaker_label_from_utterance(utterance: dict) -> str | None:
    speaker_index = utterance.get("speaker")
    if speaker_index is not None:
        return f"speaker_{speaker_index}"

    channel_value = utterance.get("channel")
    channel_index = (
        _integer_index(channel_value[0])
        if isinstance(channel_value, (list, tuple)) and channel_value
        else _integer_index(channel_value)
    )
    if channel_index is None or channel_index < 0:
        return None
    return f"Channel {channel_index + 1}"


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
    model: str | None = None,
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
    max_channels: int | None = None,
    audio_duration_seconds: float | None = None,
) -> list[TranscriptResult]:
    """Transcribe an uploaded audio file with Deepgram pre-recorded STT."""
    api_key = require_deepgram_api_key()
    resolved_content_type = DEEPGRAM_CONTENT_TYPE_ALIASES.get(content_type, content_type)

    resolved_channels = channels
    if resolved_channels is None and resolved_content_type == "audio/wav":
        resolved_channels = detect_wav_channels(audio_data)
    channel_count = max(1, resolved_channels or 1)

    # Deepgram bills per channel. Notes/meetings are mono; clamp a stereo or
    # crafted many-channel file so it cannot silently multiply per-minute cost.
    # max_channels is supplied by the dispatcher (settings.deepgram_max_channels);
    # direct callers leave it None and get no clamp.
    if isinstance(max_channels, int) and 0 < max_channels < channel_count:
        from app.core.observability import capture_sentry_anomaly

        capture_sentry_anomaly(
            "recording.file_stt.channels_clamped",
            "Clamped multichannel audio before Deepgram (per-channel billing guard)",
            category="recording",
            extras={"detected_channels": channel_count, "clamped_to": max_channels},
            level="warning",
        )
        channel_count = max_channels

    url = build_batch_url(
        language=language,
        multichannel=channel_count > 1,
        raw_pcm=resolved_content_type == "audio/raw",
        channels=channel_count,
        model=model or DEEPGRAM_BATCH_MODEL,
        keyterms=keyterms,
        replacements=replacements,
    )

    async with httpx.AsyncClient(timeout=_batch_timeout(audio_duration_seconds)) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": resolved_content_type,
            },
            content=audio_data,
        )
        response.raise_for_status()
        payload = response.json()

    return _results_from_deepgram_payload(payload)
