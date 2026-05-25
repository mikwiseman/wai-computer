"""ElevenLabs realtime voice and speech-to-text helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult, detect_wav_channels

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
SIGNED_URL_TTL_SECONDS = 15 * 60
STT_FILENAME_EXTENSIONS = {
    "audio/aac": "aac",
    "audio/flac": "flac",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/raw": "raw",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/webm": "webm",
    "audio/x-m4a": "m4a",
    "audio/x-wav": "wav",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


@dataclass(frozen=True)
class ElevenLabsSignedUrl:
    """Temporary signed conversation URL for an ElevenLabs agent."""

    signed_url: str
    agent_id: str
    expires_in_seconds: int = SIGNED_URL_TTL_SECONDS


@dataclass(frozen=True)
class ElevenLabsAgentSummary:
    """Minimal agent metadata used for runtime selection."""

    agent_id: str
    name: str | None = None


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    return settings.elevenlabs_api_key


async def list_agents(*, page_size: int = 30) -> list[ElevenLabsAgentSummary]:
    """List owned, non-archived ElevenLabs agents."""
    api_key = _require_api_key()

    async with httpx.AsyncClient(base_url=ELEVENLABS_API_BASE, timeout=15.0) as client:
        response = await client.get(
            "/v1/convai/agents",
            params={
                "page_size": page_size,
                "show_only_owned_agents": "true",
                "archived": "false",
                "sort_by": "created_at",
                "sort_direction": "asc",
            },
            headers={"xi-api-key": api_key},
        )
        response.raise_for_status()
        payload = response.json()

    agents_payload = payload.get("agents") if isinstance(payload, dict) else None
    if not isinstance(agents_payload, list):
        raise RuntimeError("ElevenLabs returned an invalid agents payload")

    agents: list[ElevenLabsAgentSummary] = []
    for item in agents_payload:
        if not isinstance(item, dict):
            continue
        agent_id = item.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        name = item.get("name")
        agents.append(
            ElevenLabsAgentSummary(
                agent_id=agent_id,
                name=name if isinstance(name, str) and name else None,
            )
        )
    return agents


async def get_signed_url(
    *,
    agent_id: str,
    include_conversation_id: bool = False,
    branch_id: str | None = None,
    environment: str | None = None,
) -> ElevenLabsSignedUrl:
    """Get a temporary signed URL for a realtime agent conversation."""
    api_key = _require_api_key()
    params: dict[str, str | bool] = {
        "agent_id": agent_id,
        "include_conversation_id": include_conversation_id,
    }
    if branch_id:
        params["branch_id"] = branch_id
    if environment:
        params["environment"] = environment

    async with httpx.AsyncClient(base_url=ELEVENLABS_API_BASE, timeout=15.0) as client:
        response = await client.get(
            "/v1/convai/conversation/get-signed-url",
            params=params,
            headers={"xi-api-key": api_key},
        )
        response.raise_for_status()
        payload = response.json()

    signed_url = payload.get("signed_url")
    if not isinstance(signed_url, str) or not signed_url:
        raise RuntimeError("ElevenLabs returned an invalid signed_url")

    return ElevenLabsSignedUrl(signed_url=signed_url, agent_id=agent_id)


def _confidence_from_words(words: list[dict[str, Any]]) -> float:
    logprobs = [
        float(word["logprob"])
        for word in words
        if isinstance(word, dict) and isinstance(word.get("logprob"), (float, int))
    ]
    if not logprobs:
        return 0.0
    avg_logprob = sum(logprobs) / len(logprobs)
    return max(0.0, min(1.0, 1.0 + (avg_logprob / 10.0)))


def _word_text(word: dict[str, Any]) -> str:
    value = word.get("text") or word.get("word")
    return str(value).strip() if value is not None else ""


def _join_word_texts(words: list[dict[str, Any]]) -> str:
    text = ""
    no_space_before = set(".,!?;:%)]}")
    no_space_after = set("([{$")

    for word in words:
        token = _word_text(word)
        if not token:
            continue
        if not text or token[0] in no_space_before or text[-1] in no_space_after:
            text += token
        else:
            text += f" {token}"

    return text.strip()


def _result_from_transcript(
    transcript: dict[str, Any],
    *,
    fallback_speaker: str | None = None,
) -> TranscriptResult | None:
    text = str(transcript.get("text", "")).strip()
    if not text:
        return None

    words = transcript.get("words") or []
    start_ms = 0
    end_ms = 0
    speaker = fallback_speaker
    confidence = 0.0
    if words:
        first_word = words[0]
        last_word = words[-1]
        start_ms = int(float(first_word.get("start", 0)) * 1000)
        end_ms = int(float(last_word.get("end", 0)) * 1000)
        speaker = first_word.get("speaker_id") or fallback_speaker
        confidence = _confidence_from_words(words)

    return TranscriptResult(
        text=text,
        speaker=speaker,
        is_final=True,
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=confidence,
    )


def _validated_words(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    if "words" not in transcript or transcript.get("words") is None:
        return []
    raw_words = transcript.get("words")
    if not isinstance(raw_words, list):
        raise RuntimeError("ElevenLabs STT returned invalid words payload")
    words: list[dict[str, Any]] = []
    for index, word in enumerate(raw_words):
        if not isinstance(word, dict):
            raise RuntimeError(f"ElevenLabs STT returned invalid word entry at index {index}")
        words.append(word)
    return words


def _results_from_transcript(
    transcript: dict[str, Any],
    *,
    fallback_speaker: str | None = None,
) -> list[TranscriptResult]:
    text_value = transcript.get("text")
    if not isinstance(text_value, str):
        raise RuntimeError("ElevenLabs STT returned invalid transcript text")
    text = text_value.strip()
    if not text:
        return []

    words = _validated_words(transcript)
    if not words or not any(_word_text(word) for word in words):
        result = _result_from_transcript(transcript, fallback_speaker=fallback_speaker)
        return [result] if result is not None else []

    results: list[TranscriptResult] = []
    current_speaker: str | None = None
    current_words: list[dict[str, Any]] = []

    def flush() -> None:
        if not current_words:
            return
        segment_text = _join_word_texts(current_words)
        if not segment_text:
            return
        first_word = current_words[0]
        last_word = current_words[-1]
        results.append(
            TranscriptResult(
                text=segment_text,
                speaker=current_speaker,
                is_final=True,
                start_ms=int(float(first_word.get("start", 0)) * 1000),
                end_ms=int(float(last_word.get("end", 0)) * 1000),
                confidence=_confidence_from_words(current_words),
            )
        )

    for word in words:
        speaker = word.get("speaker_id") or fallback_speaker
        if current_words and speaker != current_speaker:
            flush()
            current_words = []
        current_speaker = speaker
        current_words.append(word)

    flush()
    return results


def _stt_upload_filename(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    extension = STT_FILENAME_EXTENSIONS.get(normalized)
    if not extension:
        raise ValueError(f"Unsupported ElevenLabs STT content type: {content_type}")
    return f"recording.{extension}"


def _stt_language_code(language: str | None) -> str | None:
    normalized = (language or "").strip().lower()
    if not normalized or normalized in {"auto", "multi", "und"}:
        return None
    return normalized


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
    model: str | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file with ElevenLabs Speech-to-Text."""
    settings = get_settings()
    api_key = _require_api_key()
    resolved_channels = channels
    if resolved_channels is None and content_type == "audio/wav":
        resolved_channels = detect_wav_channels(audio_data)

    form_data: dict[str, Any] = {
        "model_id": model or settings.elevenlabs_speech_to_text_model,
        "timestamps_granularity": "word",
        "diarize": "true" if (resolved_channels or 1) <= 1 else "false",
        "tag_audio_events": "true",
    }
    if settings.elevenlabs_no_verbatim:
        form_data["no_verbatim"] = "true"
    language_code = _stt_language_code(language)
    if language_code:
        form_data["language_code"] = language_code
    if resolved_channels and resolved_channels > 1:
        form_data["use_multi_channel"] = "true"
    if content_type == "audio/raw" and (resolved_channels or 1) == 1:
        form_data["file_format"] = "pcm_s16le_16"

    files = {
        "file": (_stt_upload_filename(content_type), audio_data, content_type),
    }

    async with httpx.AsyncClient(base_url=ELEVENLABS_API_BASE, timeout=300.0) as client:
        response = await client.post(
            "/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            data=form_data,
            files=files,
        )
        response.raise_for_status()
        payload = response.json()

    if isinstance(payload, dict):
        transcripts = payload.get("transcripts")
    else:
        transcripts = None

    if isinstance(transcripts, list):
        results = []
        for index, transcript in enumerate(transcripts, start=1):
            if not isinstance(transcript, dict):
                raise RuntimeError(
                    f"ElevenLabs STT returned invalid transcript entry at index {index}"
                )
            results.extend(
                _results_from_transcript(transcript, fallback_speaker=f"Channel {index}")
            )
        return results

    if isinstance(payload, dict):
        return _results_from_transcript(payload)

    raise RuntimeError(
        f"ElevenLabs STT returned unexpected payload type={type(payload).__name__}"
    )
