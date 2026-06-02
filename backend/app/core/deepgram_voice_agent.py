"""Deepgram Voice Agent ``Settings`` builder (hands-free orchestration, Layer B).

Deepgram's Voice Agent API runs the whole real-time loop in one WebSocket —
listen (STT) → think (LLM) → speak (TTS) — with built-in barge-in and
end-of-turn detection. We point its ``think`` at our own brain via the
OpenAI-compatible custom-LLM bridge, so Deepgram orchestrates the conversation
while WaiComputer stays the LLM. This consolidates voice on a vendor we already
run (nova-3 STT, cost guard) instead of adding a second orchestration brain.

The one gap: Deepgram Aura-2 TTS speaks 7 languages and **not Russian**. So for
Russian (and any non-Aura language) the caller must supply an explicit
non-Deepgram voice (ElevenLabs/Cartesia) — we never silently emit a
wrong-language voice (no fallbacks).

This module only builds the ``Settings`` config (pure, testable). Connecting the
WebSocket + the Deepgram auth token are client/deploy concerns.
"""

from __future__ import annotations

from dataclasses import dataclass

# Languages Deepgram Aura-2 TTS can speak (verified June 2026). Russian is NOT
# among them — hence the explicit-voice requirement below.
AURA_LANGUAGES = frozenset({"en", "es", "nl", "fr", "de", "it", "ja"})

DEFAULT_LISTEN_MODEL = "nova-3"  # RU-capable multilingual STT we already run
DEFAULT_AURA_EN_MODEL = "aura-2-thalia-en"

BRIDGE_PATH = "/api/voice/llm/chat/completions"

DEFAULT_INPUT_SAMPLE_RATE = 16000
DEFAULT_OUTPUT_SAMPLE_RATE = 24000


class UnsupportedVoiceLanguageError(ValueError):
    """The requested language has no Deepgram Aura voice and no explicit voice
    was supplied — surfaced rather than emitting a wrong-language voice."""


@dataclass(frozen=True)
class VoiceAgentTTS:
    """The agent's ``speak`` provider. ``deepgram`` uses Aura (Aura languages
    only); ``eleven_labs``/``cartesia`` carry a Russian-capable voice id and need
    a deploy-configured endpoint (added by the route, not here)."""

    provider: str
    model: str | None = None  # Deepgram Aura model name
    model_id: str | None = None  # ElevenLabs / Cartesia voice id
    language: str | None = None

    def to_speak_block(self) -> dict:
        provider: dict[str, object] = {"type": self.provider}
        if self.model is not None:
            provider["model"] = self.model
        if self.model_id is not None:
            provider["model_id"] = self.model_id
        if self.language is not None:
            provider["language"] = self.language
        return {"provider": provider}


def default_tts_for_language(language: str) -> VoiceAgentTTS:
    """Pick Deepgram Aura for an Aura language; raise for the rest so the caller
    supplies a Russian-capable voice explicitly."""
    if language in AURA_LANGUAGES:
        model = DEFAULT_AURA_EN_MODEL if language == "en" else None
        return VoiceAgentTTS(provider="deepgram", model=model, language=language)
    raise UnsupportedVoiceLanguageError(
        f"Deepgram Aura has no '{language}' voice; supply an explicit TTS voice "
        f"(e.g. ElevenLabs/Cartesia) for this language"
    )


def build_voice_agent_settings(
    *,
    bridge_url: str,
    voice_token: str,
    language: str = "en",
    tts: VoiceAgentTTS | None = None,
    greeting: str | None = None,
    input_sample_rate: int = DEFAULT_INPUT_SAMPLE_RATE,
    output_sample_rate: int = DEFAULT_OUTPUT_SAMPLE_RATE,
) -> dict:
    """Build the Deepgram Voice Agent ``Settings`` message.

    ``think`` points at our custom-LLM bridge with the per-session voice token as
    a Bearer header (Deepgram presents it when calling the bridge). ``listen`` is
    Deepgram nova-3; ``speak`` is the resolved TTS (Aura by default; explicit for
    Russian).
    """
    speak = (tts or default_tts_for_language(language)).to_speak_block()

    agent: dict[str, object] = {
        "listen": {
            "provider": {
                "type": "deepgram",
                "model": DEFAULT_LISTEN_MODEL,
                "language": language,
            }
        },
        "think": {
            "provider": {"type": "open_ai"},
            "endpoint": {
                "url": bridge_url,
                "headers": {"authorization": f"Bearer {voice_token}"},
            },
        },
        "speak": speak,
    }
    if greeting is not None:
        agent["greeting"] = greeting

    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": input_sample_rate},
            "output": {
                "encoding": "linear16",
                "sample_rate": output_sample_rate,
                "container": "none",
            },
        },
        "agent": agent,
    }
