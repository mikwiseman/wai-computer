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


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file with ElevenLabs Speech-to-Text."""
    settings = get_settings()
    api_key = _require_api_key()
    resolved_channels = channels
    if resolved_channels is None and content_type == "audio/wav":
        resolved_channels = detect_wav_channels(audio_data)

    form_data: dict[str, Any] = {
        "model_id": settings.elevenlabs_speech_to_text_model,
        "timestamps_granularity": "word",
        "diarize": "true" if (resolved_channels or 1) <= 1 else "false",
        "tag_audio_events": "true",
    }
    if settings.elevenlabs_no_verbatim:
        form_data["no_verbatim"] = "true"
    if language and language != "multi":
        form_data["language_code"] = language
    if resolved_channels and resolved_channels > 1:
        form_data["use_multi_channel"] = "true"
    if content_type == "audio/raw" and (resolved_channels or 1) == 1:
        form_data["file_format"] = "pcm_s16le_16"

    files = {
        "file": ("recording", audio_data, content_type),
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
                continue
            result = _result_from_transcript(transcript, fallback_speaker=f"Channel {index}")
            if result is not None:
                results.append(result)
        return results

    if isinstance(payload, dict):
        single = _result_from_transcript(payload)
        return [single] if single is not None else []

    logger.warning("Unexpected ElevenLabs STT payload type=%s", type(payload).__name__)
    return []
