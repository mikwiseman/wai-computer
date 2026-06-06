"""Cross-modal intent routing for Telegram voice notes.

The bot's primary job is "send a voice note → get a recording in your library".
But the same chat is also where the user *talks to* Wai. Historically modality
decided intent (voice → always a recording, text → the agent), so a spoken command
like "сколько будет 1+2" was filed instead of answered. This module decides, per
voice note, whether the user is **filling their library** (file it) or **talking to
the assistant** (route the transcript through the normal text pipeline).

Two tiers, cheap → expensive, mirroring how Hermes ("act on the obvious default")
and OpenClaw (a deterministic inbound-event gate) actually route 1:1 chat:

1. ``route_voice_by_metadata`` — Telegram metadata only, no STT, no LLM. Resolves
   the confident cases (non-voice media, forwarded audio, long-form, replies to the
   bot). Returns ``None`` when only the spoken content can decide.
2. ``classify_voice_transcript`` — a small Cerebras classifier over the transcript,
   biased to ``file`` whenever it is not reasonably sure the user addressed Wai.
   Filing is lossless and reversible; misrouting a real recording to chat is not, so
   the safe default is always to file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.config import get_settings
from app.core.cerebras_chat import (
    chat_completion_parsed,
    get_cerebras_client,
    strict_json_response_format,
)

logger = logging.getLogger(__name__)

VoiceRoute = Literal["file", "message"]


@dataclass(frozen=True)
class VoiceRouteDecision:
    """Where a voice note should go.

    ``route`` is ``"file"`` (save as a library recording) or ``"message"`` (treat the
    transcript as if the user had typed it — agent / command / search). ``reason`` is
    a short machine tag for logs/telemetry, never shown to the user.
    """

    route: VoiceRoute
    reason: str


class _VoiceIntentSchema(BaseModel):
    target: Literal["assistant", "library"]
    confidence: Literal["high", "medium", "low"]
    reason: str


def route_voice_by_metadata(
    *,
    kind: str,
    duration_seconds: float | None,
    is_forwarded: bool,
    is_reply_to_assistant: bool,
    max_command_seconds: int,
) -> VoiceRouteDecision | None:
    """Deterministic gate from Telegram metadata alone.

    Returns a decision for the confident cases, or ``None`` when the spoken content
    is needed to decide (short, non-forwarded voice that is not a reply to the bot).
    """
    if kind != "voice":
        # Only Telegram voice notes — the thing people naturally "talk" with — are
        # ever treated as possible commands. Audio/video files, video notes and
        # audio documents stay library recordings exactly as before.
        return VoiceRouteDecision("file", "non_voice_media")
    if is_forwarded:
        # Forwarded audio is something the user is archiving, not saying to Wai.
        return VoiceRouteDecision("file", "forwarded")
    if is_reply_to_assistant:
        # Replying to Wai's own message is unambiguously conversational.
        return VoiceRouteDecision("message", "reply_to_assistant")
    if duration_seconds is not None and duration_seconds >= max_command_seconds:
        # Long-form audio is a recording; never risk losing one to a misclassification.
        return VoiceRouteDecision("file", "long_form")
    return None


async def classify_voice_transcript(
    transcript_text: str,
    *,
    recent_assistant_message: str | None = None,
) -> VoiceRouteDecision:
    """Classify a short voice note's transcript: addressed to Wai, or a library note?

    Biased to ``file``: ``message`` is returned only when the model is reasonably
    confident the user addressed the assistant. Any classifier failure also routes to
    ``file`` — the lossless, historical default — with a distinct ``reason`` so the
    degradation is observable rather than silent.
    """
    text = (transcript_text or "").strip()
    if not text:
        return VoiceRouteDecision("file", "empty_transcript")

    settings = get_settings()
    if not settings.cerebras_api_key:
        return VoiceRouteDecision("file", "classifier_unconfigured")

    client = get_cerebras_client()
    user_block = (
        f'Wai\'s previous message: "{recent_assistant_message.strip()[:400]}"\n\n'
        if recent_assistant_message and recent_assistant_message.strip()
        else ""
    )
    user_block += f'User\'s voice message: "{text[:1200]}"'
    try:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_PROMPT},
                {"role": "user", "content": user_block},
            ],
            response_format=strict_json_response_format(
                _VoiceIntentSchema, name="voice_intent"
            ),
            reasoning_effort="low",
            max_completion_tokens=512,
        )
        parsed = chat_completion_parsed(
            response, _VoiceIntentSchema, operation="Voice intent"
        )
    except Exception as exc:  # noqa: BLE001 — any classifier failure routes to the safe default
        logger.warning("voice intent classification failed error=%s", type(exc).__name__)
        return VoiceRouteDecision("file", "classifier_error")

    if parsed.target == "assistant" and parsed.confidence in {"high", "medium"}:
        return VoiceRouteDecision("message", f"assistant_{parsed.confidence}")
    return VoiceRouteDecision("file", f"{parsed.target}_{parsed.confidence}")


_CLASSIFIER_PROMPT = """\
You route a single short VOICE message sent to Wai, a voice-first "second brain"
assistant, through its Telegram bot. Decide who the message is addressed to.

- "assistant": the user is talking TO Wai — asking a question, giving a command or
  request, or reacting to Wai — and expects a response or an action. Examples:
  "сколько будет два плюс два", "напомни позвонить маме в пять", "найди где я
  говорил про бюджет", "какие у меня встречи сегодня", "переведи это на английский",
  "проверь, как ты принимаешь голосовые сообщения", "summarize my last meeting".
- "library": the user is dictating a note, thought, reflection, journal entry,
  meeting log, or recorded monologue they want SAVED — not addressed to anyone, no
  response expected. Examples: "Сегодня обсудили роадмап, решили перенести релиз...",
  a brain-dump of ideas, a recorded conversation.

Rules:
- Judge by WHO the utterance is addressed to and whether it expects a response or
  action — not by length alone. A long request to the assistant is still "assistant";
  a short self-note is still "library".
- A reaction or instruction aimed at Wai (test, check, do, find, remind, translate,
  answer) is "assistant".
- When genuinely unsure, choose "library" with low confidence — saving is always
  safe and reversible, answering instead of saving is not.

Return JSON: {"target": "assistant"|"library", "confidence": "high"|"medium"|"low",
"reason": "<= 8 words"}.
"""
