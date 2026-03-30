"""Intent Router — classifies user messages and routes to the right handler.

Uses pattern matching first (instant, free), falls back to Haiku for ambiguous messages.
"""

import logging
from enum import StrEnum

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)


class Intent(StrEnum):
    SEARCH = "search"
    VOICE_SUMMARY = "voice_summary"
    DIGEST = "digest"
    ACTION = "action"
    BUILD = "build"
    EDIT = "edit"
    COACH = "coach"
    CHAT = "chat"


CLASSIFICATION_PROMPT = """Classify the user's message into exactly ONE intent. Respond with ONLY the intent name, nothing else.

Intents:
- search: user wants to find something in their recordings or messages ("what did X say?", "find the discussion about Y")
- voice_summary: user sent a voice message and wants a summary
- digest: user wants a daily/weekly summary of their activity
- action: user wants to perform an action (send email, create event)
- build: user wants to create something (website, app, landing page, tracker, presentation)
- edit: user wants to modify something that was previously created
- coach: user wants to learn about AI, prompting, or tools
- chat: general conversation, questions, brainstorming

User message: {message}
"""


async def classify_intent(message: str, has_voice: bool = False) -> Intent:
    """Classify a user message into an intent."""
    if has_voice:
        return Intent.VOICE_SUMMARY

    lower = message.lower().strip()

    # Natural language patterns (skip LLM for obvious intents)
    search_keywords = [
        "search for", "find ", "what did", "when did", "who said",
        "найди", "поищи", "что говорил", "что обсуждали", "когда",
        "where is", "show me", "look for", "покажи", "где ",
    ]
    if any(lower.startswith(kw) or f" {kw}" in lower for kw in search_keywords):
        return Intent.SEARCH

    digest_keywords = [
        "digest", "summary of", "what happened", "дайджест", "что было", "итоги",
    ]
    if any(kw in lower for kw in digest_keywords):
        return Intent.DIGEST

    build_keywords = [
        "build ", "create ", "deploy ", "make a site", "make a ", "make an app",
        "построй", "создай", "задеплой", "сделай сайт", "сделай бот",
        "сделай трекер", "сделай приложение", "трекер ", "tracker",
    ]
    if any(kw in lower for kw in build_keywords):
        return Intent.BUILD

    edit_keywords = [
        "change ", "modify ", "update ", "add ", "remove ", "make it ", "make the ",
        "replace ", "fix the ", "измени", "поменяй", "добавь", "убери",
        "сделай ", "замени", "поправь", "обнови",
        "darker", "lighter", "bigger", "smaller",
        "темнее", "светлее", "крупнее", "меньше",
    ]
    if any(lower.startswith(kw) or kw in lower for kw in edit_keywords):
        return Intent.EDIT

    action_keywords = [
        "send email", "send a message", "create event", "schedule",
        "отправь письмо", "отправь сообщение", "создай событие", "запланируй",
    ]
    if any(kw in lower for kw in action_keywords):
        return Intent.ACTION

    commitment_keywords = [
        "what did i promise", "what do i owe", "my commitments",
        "что я обещал", "мои обязательства", "что должен",
        "what did they promise", "who owes me",
    ]
    if any(kw in lower for kw in commitment_keywords):
        return Intent.SEARCH

    # LLM classification for ambiguous messages
    try:
        settings = get_settings()
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.agent_model,
            max_tokens=20,
            messages=[
                {"role": "user", "content": CLASSIFICATION_PROMPT.format(message=message[:500])},
            ],
        )
        intent_text = response.content[0].text.strip().lower()

        for intent in Intent:
            if intent.value in intent_text:
                return intent

        return Intent.CHAT
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to chat: {e}")
        return Intent.CHAT


def get_model_for_intent(intent: Intent) -> str:
    """Get the appropriate model for the classified intent."""
    settings = get_settings()
    if intent == Intent.BUILD:
        return settings.anthropic_model  # Sonnet for code generation
    return settings.agent_model  # Haiku for everything else
