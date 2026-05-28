"""Deepgram realtime speech-to-text helpers."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from app.config import get_settings

DEEPGRAM_REALTIME_WS_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_REALTIME_MODEL = "nova-3"
DEEPGRAM_REALTIME_SAMPLE_RATE = 16_000
DEEPGRAM_REALTIME_CHANNELS = 1
DEEPGRAM_REALTIME_ENCODING = "linear16"
DEEPGRAM_KEEP_ALIVE_INTERVAL_SECONDS = 4
DEEPGRAM_UTTERANCE_END_MS = 1_000
DEEPGRAM_ENDPOINTING_MS = 300
DEEPGRAM_MULTILINGUAL_ENDPOINTING_MS = 100

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


def build_realtime_websocket_url(
    *,
    language: str,
    channels: int,
    purpose: Literal["recording", "dictation"],
    model: str = DEEPGRAM_REALTIME_MODEL,
) -> str:
    resolved_language = normalize_deepgram_language(language)
    params: list[tuple[str, str | int]] = [
        ("model", model),
        ("encoding", DEEPGRAM_REALTIME_ENCODING),
        ("sample_rate", DEEPGRAM_REALTIME_SAMPLE_RATE),
        ("channels", max(1, channels)),
        ("language", resolved_language),
        ("interim_results", "true"),
        ("smart_format", "true"),
        ("vad_events", "true"),
        ("utterance_end_ms", DEEPGRAM_UTTERANCE_END_MS),
        (
            "endpointing",
            DEEPGRAM_MULTILINGUAL_ENDPOINTING_MS
            if resolved_language == "multi"
            else DEEPGRAM_ENDPOINTING_MS,
        ),
    ]
    if purpose == "recording":
        params.append(("utterances", "true"))
        params.append(("diarize", "true"))
    if purpose == "dictation" and supports_dictation(resolved_language):
        params.extend((("dictation", "true"), ("punctuate", "true")))
    if supports_numerals(resolved_language):
        params.append(("numerals", "true"))
    return f"{DEEPGRAM_REALTIME_WS_URL}?{urlencode(params)}"
