"""Tests for realtime voice provider abstraction."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.elevenlabs import ElevenLabsSignedUrl


@pytest.mark.asyncio
async def test_create_realtime_voice_session_uses_conversation_agent():
    with (
        patch("app.core.voice_runtime.get_settings") as mock_settings,
        patch(
            "app.core.voice_runtime.get_signed_url",
            new=AsyncMock(
                return_value=ElevenLabsSignedUrl(
                    signed_url="wss://signed.example",
                    agent_id="agent-conv",
                )
            ),
        ) as mock_signed_url,
    ):
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "production"
        mock_settings.return_value.elevenlabs_conversation_agent_id = "agent-conv"
        mock_settings.return_value.elevenlabs_recording_agent_id = "agent-rec"

        from app.core.voice_runtime import create_realtime_voice_session

        result = await create_realtime_voice_session(mode="conversation")

    assert result.provider == "elevenlabs"
    assert result.mode == "conversation"
    assert result.agent_id == "agent-conv"
    assert result.signed_url == "wss://signed.example"
    mock_signed_url.assert_awaited_once_with(
        agent_id="agent-conv",
        include_conversation_id=False,
        branch_id=None,
        environment="production",
    )


@pytest.mark.asyncio
async def test_create_realtime_voice_session_uses_recording_agent():
    with (
        patch("app.core.voice_runtime.get_settings") as mock_settings,
        patch(
            "app.core.voice_runtime.get_signed_url",
            new=AsyncMock(
                return_value=ElevenLabsSignedUrl(
                    signed_url="wss://recording.example",
                    agent_id="agent-rec",
                )
            ),
        ) as mock_signed_url,
    ):
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "staging"
        mock_settings.return_value.elevenlabs_conversation_agent_id = "agent-conv"
        mock_settings.return_value.elevenlabs_recording_agent_id = "agent-rec"

        from app.core.voice_runtime import create_realtime_voice_session

        result = await create_realtime_voice_session(
            mode="recording",
            include_conversation_id=True,
            branch_id="branch-1",
        )

    assert result.environment == "staging"
    assert result.branch_id == "branch-1"
    mock_signed_url.assert_awaited_once_with(
        agent_id="agent-rec",
        include_conversation_id=True,
        branch_id="branch-1",
        environment="staging",
    )


@pytest.mark.asyncio
async def test_create_realtime_voice_session_respects_explicit_agent_id():
    with (
        patch("app.core.voice_runtime.get_settings") as mock_settings,
        patch(
            "app.core.voice_runtime.get_signed_url",
            new=AsyncMock(
                return_value=ElevenLabsSignedUrl(
                    signed_url="wss://explicit.example",
                    agent_id="agent-explicit",
                )
            ),
        ) as mock_signed_url,
    ):
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "production"
        mock_settings.return_value.elevenlabs_conversation_agent_id = "agent-conv"
        mock_settings.return_value.elevenlabs_recording_agent_id = "agent-rec"

        from app.core.voice_runtime import create_realtime_voice_session

        result = await create_realtime_voice_session(
            mode="conversation",
            agent_id="agent-explicit",
        )

    assert result.agent_id == "agent-explicit"
    mock_signed_url.assert_awaited_once_with(
        agent_id="agent-explicit",
        include_conversation_id=False,
        branch_id=None,
        environment="production",
    )


@pytest.mark.asyncio
async def test_create_realtime_voice_session_rejects_unknown_provider():
    with patch("app.core.voice_runtime.get_settings") as mock_settings:
        mock_settings.return_value.realtime_voice_provider = "other"
        mock_settings.return_value.elevenlabs_environment = "production"

        from app.core.voice_runtime import create_realtime_voice_session

        with pytest.raises(ValueError, match="Unsupported realtime_voice_provider"):
            await create_realtime_voice_session(mode="conversation")


@pytest.mark.asyncio
async def test_create_realtime_voice_session_requires_agent_configuration():
    with patch("app.core.voice_runtime.get_settings") as mock_settings:
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "production"
        mock_settings.return_value.elevenlabs_conversation_agent_id = ""
        mock_settings.return_value.elevenlabs_recording_agent_id = ""

        with patch(
            "app.core.voice_runtime.list_agents",
            new=AsyncMock(return_value=[]),
        ):
            from app.core.voice_runtime import create_realtime_voice_session

            with pytest.raises(ValueError, match="No ElevenLabs agent configured"):
                await create_realtime_voice_session(mode="conversation")


@pytest.mark.asyncio
async def test_create_realtime_voice_session_auto_resolves_single_agent():
    with (
        patch("app.core.voice_runtime.get_settings") as mock_settings,
        patch(
            "app.core.voice_runtime.get_signed_url",
            new=AsyncMock(
                return_value=ElevenLabsSignedUrl(
                    signed_url="wss://auto.example",
                    agent_id="agent-auto",
                )
            ),
        ) as mock_signed_url,
        patch(
            "app.core.voice_runtime.list_agents",
            new=AsyncMock(return_value=[type("Agent", (), {"agent_id": "agent-auto"})()]),
        ),
    ):
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "production"
        mock_settings.return_value.elevenlabs_conversation_agent_id = ""
        mock_settings.return_value.elevenlabs_recording_agent_id = ""

        from app.core.voice_runtime import create_realtime_voice_session

        result = await create_realtime_voice_session(mode="conversation")

    assert result.agent_id == "agent-auto"
    mock_signed_url.assert_awaited_once_with(
        agent_id="agent-auto",
        include_conversation_id=False,
        branch_id=None,
        environment="production",
    )


@pytest.mark.asyncio
async def test_create_realtime_voice_session_rejects_multiple_auto_discovered_agents():
    with (
        patch("app.core.voice_runtime.get_settings") as mock_settings,
        patch(
            "app.core.voice_runtime.list_agents",
            new=AsyncMock(
                return_value=[
                    type("Agent", (), {"agent_id": "agent-1"})(),
                    type("Agent", (), {"agent_id": "agent-2"})(),
                ]
            ),
        ),
    ):
        mock_settings.return_value.realtime_voice_provider = "elevenlabs"
        mock_settings.return_value.elevenlabs_environment = "production"
        mock_settings.return_value.elevenlabs_conversation_agent_id = ""
        mock_settings.return_value.elevenlabs_recording_agent_id = ""

        from app.core.voice_runtime import create_realtime_voice_session

        with pytest.raises(ValueError, match="Multiple ElevenLabs agents found"):
            await create_realtime_voice_session(mode="conversation")
