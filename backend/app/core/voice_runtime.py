"""Provider abstraction for realtime voice sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.core.elevenlabs import get_signed_url, list_agents

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeVoiceSession:
    """Connection details for a provider-backed realtime voice session."""

    provider: str
    mode: str
    agent_id: str
    signed_url: str
    expires_in_seconds: int
    environment: str | None = None
    branch_id: str | None = None


async def create_realtime_voice_session(
    *,
    mode: str,
    agent_id: str | None = None,
    include_conversation_id: bool = False,
    branch_id: str | None = None,
    environment: str | None = None,
) -> RealtimeVoiceSession:
    """Create a new realtime voice session using the configured provider."""
    settings = get_settings()
    provider = settings.realtime_voice_provider.strip().lower()
    resolved_environment = environment or settings.elevenlabs_environment
    logger.info(
        "resolving realtime voice session provider=%s mode=%s branch_id=%s",
        provider,
        mode,
        branch_id,
    )

    if provider != "elevenlabs":
        raise ValueError(f"Unsupported realtime_voice_provider: {provider}")

    if agent_id:
        resolved_agent_id = agent_id
    elif mode == "recording":
        resolved_agent_id = (
            settings.elevenlabs_recording_agent_id
            or settings.elevenlabs_conversation_agent_id
        )
    else:
        resolved_agent_id = settings.elevenlabs_conversation_agent_id

    if not resolved_agent_id:
        agents = await list_agents(page_size=2)
        if len(agents) == 1:
            resolved_agent_id = agents[0].agent_id
            logger.info(
                "resolved realtime voice agent automatically mode=%s agent_id=%s",
                mode,
                resolved_agent_id,
            )
        elif len(agents) > 1:
            raise ValueError(
                "Multiple ElevenLabs agents found. Configure "
                "ELEVENLABS_CONVERSATION_AGENT_ID or pass agent_id explicitly."
            )
        else:
            raise ValueError(f"No ElevenLabs agent configured for realtime voice mode: {mode}")

    logger.info(
        "requesting realtime voice signed url provider=%s mode=%s agent_id=%s",
        provider,
        mode,
        resolved_agent_id,
    )

    signed = await get_signed_url(
        agent_id=resolved_agent_id,
        include_conversation_id=include_conversation_id,
        branch_id=branch_id,
        environment=resolved_environment,
    )

    return RealtimeVoiceSession(
        provider=provider,
        mode=mode,
        agent_id=signed.agent_id,
        signed_url=signed.signed_url,
        expires_in_seconds=signed.expires_in_seconds,
        environment=resolved_environment,
        branch_id=branch_id,
    )
