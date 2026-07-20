"""OpenAI Realtime transcription session support for live dictation.

Dictation streams through the WaiComputer realtime proxy to the OpenAI
Realtime API (GA, mid-2026) running ``gpt-realtime-whisper`` — a natively
streaming STT model. The proxy translates between the WaiComputer client wire
protocol (binary PCM16 frames + ``Finalize``/``CloseStream``/``KeepAlive``
control messages, Deepgram-shaped ``Results`` frames back) and the OpenAI
event protocol, so every platform client keeps a single wire protocol.

Protocol facts verified against the live API on 2026-07-20:

- URL: ``wss://api.openai.com/v1/realtime?intent=transcription`` with a
  standard ``Authorization: Bearer`` header (the beta header died with the
  beta interface in May 2026).
- Session config is one ``session.update`` with ``session.type:
  "transcription"``; audio is ``audio/pcm`` at 24 kHz mono PCM16.
- ``gpt-realtime-whisper`` rejects ``turn_detection`` ("Turn detection is not
  supported for this transcription model") — the session runs VAD-less and
  the proxy commits manually when the client finalizes.
- Transcript deltas stream continuously during speech
  (``conversation.item.input_audio_transcription.delta``); the final
  transcript arrives as ``...transcription.completed`` roughly 0.6 s after
  ``input_audio_buffer.commit`` at ``delay: "high"``.
- Committing under ~100 ms of buffered audio fails with
  ``input_audio_buffer_commit_empty`` — the proxy must treat that as an
  empty, successful finalization, not an error.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

OPENAI_REALTIME_WEBSOCKET_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
OPENAI_REALTIME_MODEL = "gpt-realtime-whisper"
OPENAI_REALTIME_SAMPLE_RATE = 24_000
OPENAI_REALTIME_CHANNELS = 1
OPENAI_REALTIME_ENCODING = "linear16"
# Accuracy-first: "high" keeps live preview deltas flowing while giving the
# model more context per token. Verified commit→completed ≈ 0.6 s, and
# noticeably better RU/EN code-switching than "low" on the same audio.
OPENAI_REALTIME_TRANSCRIPTION_DELAY = "high"
OPENAI_REALTIME_NOISE_REDUCTION = "near_field"
# OpenAI rejects commits with under 100 ms of audio; leave headroom.
OPENAI_REALTIME_MIN_COMMIT_MS = 120
OPENAI_REALTIME_COMMIT_EMPTY_CODE = "input_audio_buffer_commit_empty"

_VALID_TRANSCRIPTION_DELAYS = frozenset({"minimal", "low", "medium", "high", "xhigh"})


def require_openai_api_key() -> str:
    key = (get_settings().openai_api_key or "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return key


def normalize_openai_realtime_language(language: str | None) -> str | None:
    """Map the client language surface to an OpenAI ISO-639-1 hint.

    Clients send ``multi`` (auto-detect) or an ISO code, sometimes
    region-qualified (``en-US``). OpenAI wants a bare ISO-639-1 hint and
    auto-detects (including intra-utterance code-switching) when omitted.
    """
    normalized = (language or "").strip().lower()
    if normalized in {"", "auto", "und", "multi"}:
        return None
    return normalized.split("-", 1)[0]


def openai_realtime_transcription_delay() -> str:
    delay = (get_settings().openai_realtime_transcription_delay or "").strip().lower()
    if delay not in _VALID_TRANSCRIPTION_DELAYS:
        raise ValueError(
            f"Unsupported openai_realtime_transcription_delay: {delay!r}. "
            f"Expected one of {sorted(_VALID_TRANSCRIPTION_DELAYS)}."
        )
    return delay


def build_transcription_session_update(
    *,
    model: str,
    language: str | None,
) -> dict[str, Any]:
    """Build the ``session.update`` payload for a dictation session.

    ``turn_detection`` stays explicitly ``null``: gpt-realtime-whisper rejects
    VAD configs, and the dictation flow commits manually on Finalize.
    """
    transcription: dict[str, Any] = {"model": model}
    resolved_language = normalize_openai_realtime_language(language)
    if resolved_language is not None:
        transcription["language"] = resolved_language
    if model == OPENAI_REALTIME_MODEL:
        transcription["delay"] = openai_realtime_transcription_delay()
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
                    "noise_reduction": {"type": OPENAI_REALTIME_NOISE_REDUCTION},
                    "turn_detection": None,
                },
            },
        },
    }


def map_openai_error_code(code: str | None) -> str:
    """Translate OpenAI realtime error codes into the client error vocabulary.

    Native clients map ``err_code`` strings onto typed provider errors
    (auth/quota/rate-limit/internal); reuse the codes they already know.
    """
    normalized = (code or "").strip().lower()
    if normalized in {"invalid_api_key", "invalid_authentication", "unauthorized"}:
        return "authentication_error"
    if normalized in {"insufficient_quota", "billing_hard_limit_reached"}:
        return "insufficient_quota"
    if normalized in {"rate_limit_exceeded", "requests_limit_reached", "too_many_requests"}:
        return "rate_limit_exceeded"
    if normalized in {"invalid_model", "model_not_found"}:
        return "unsupported_model"
    return normalized or "provider_error"
