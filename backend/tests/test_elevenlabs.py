"""Tests for ElevenLabs realtime voice agent helpers."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.elevenlabs import (
    ElevenLabsAgentSummary,
    ElevenLabsSignedUrl,
    get_signed_url,
    list_agents,
)


@pytest.mark.asyncio
async def test_get_signed_url_returns_expected_payload():
    response = httpx.Response(
        200,
        json={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent-1"},
        request=httpx.Request(
            "GET",
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        ),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        signed_url = await get_signed_url(agent_id="agent-1", environment="production")

    assert signed_url == ElevenLabsSignedUrl(
        signed_url="wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent-1",
        agent_id="agent-1",
    )


@pytest.mark.asyncio
async def test_get_signed_url_rejects_missing_payload_value():
    response = httpx.Response(
        200,
        json={},
        request=httpx.Request(
            "GET",
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        ),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        with pytest.raises(RuntimeError, match="invalid signed_url"):
            await get_signed_url(agent_id="agent-1", branch_id="branch-1")


@pytest.mark.asyncio
async def test_list_agents_returns_owned_agents():
    response = httpx.Response(
        200,
        json={
            "agents": [
                {"agent_id": "agent-1", "name": "Wai Primary"},
                {"agent_id": "agent-2", "name": "Wai Backup"},
            ]
        },
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        agents = await list_agents(page_size=2)

    assert agents == [
        ElevenLabsAgentSummary(agent_id="agent-1", name="Wai Primary"),
        ElevenLabsAgentSummary(agent_id="agent-2", name="Wai Backup"),
    ]


@pytest.mark.asyncio
async def test_list_agents_skips_invalid_entries():
    response = httpx.Response(
        200,
        json={
            "agents": [
                "bad-entry",
                {"name": "Missing id"},
                {"agent_id": "agent-3", "name": "Wai Valid"},
            ]
        },
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        agents = await list_agents()

    assert agents == [ElevenLabsAgentSummary(agent_id="agent-3", name="Wai Valid")]


@pytest.mark.asyncio
async def test_list_agents_rejects_invalid_payload():
    response = httpx.Response(
        200,
        json={},
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/convai/agents"),
    )

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "key"
        with pytest.raises(RuntimeError, match="invalid agents payload"):
            await list_agents()
