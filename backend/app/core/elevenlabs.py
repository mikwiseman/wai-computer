"""ElevenLabs realtime voice agent helpers.

Speech-to-text moved to Deepgram (see ``app/core/deepgram.py``); this module now
only covers the realtime conversational voice agents (signed URLs + agent listing).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

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
