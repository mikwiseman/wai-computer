"""Extended tests for agent chat route — error cases and edge scenarios."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestAgentChatErrors:
    @patch("app.api.routes.agent_chat.get_settings")
    async def test_no_api_key_returns_503(
        self, mock_get_settings, client: AsyncClient, auth_headers: dict,
    ):
        mock_settings = AsyncMock()
        mock_settings.anthropic_api_key = ""
        mock_get_settings.return_value = mock_settings

        response = await client.post(
            "/api/agent/chat",
            json={"message": "hello"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    async def test_message_too_long(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/agent/chat",
            json={"message": "x" * 10001},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_missing_message_field(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/agent/chat",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 422

    @patch("app.api.routes.agent_chat.get_settings")
    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_with_session_id(
        self, mock_router_anthropic, mock_get_loop_client, mock_get_settings,
        client: AsyncClient, auth_headers: dict,
    ):
        mock_settings = AsyncMock()
        mock_settings.anthropic_api_key = "test-key"
        mock_get_settings.return_value = mock_settings

        mock_router_client = AsyncMock()
        mock_router_anthropic.return_value = mock_router_client
        mock_router_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="chat")]
        )

        mock_loop_client = AsyncMock()
        mock_get_loop_client.return_value = mock_loop_client
        mock_loop_client.messages.create.return_value = AsyncMock(
            stop_reason="end_turn",
            content=[AsyncMock(text="Hi!", type="text")],
            usage=AsyncMock(input_tokens=50, output_tokens=20),
        )

        response = await client.post(
            "/api/agent/chat",
            json={"message": "hello", "session_id": "my-session-123"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "my-session-123"

    @patch("app.api.routes.agent_chat.get_settings")
    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_with_voice_transcript(
        self, mock_router_anthropic, mock_get_loop_client, mock_get_settings,
        client: AsyncClient, auth_headers: dict,
    ):
        mock_settings = AsyncMock()
        mock_settings.anthropic_api_key = "test-key"
        mock_get_settings.return_value = mock_settings

        mock_loop_client = AsyncMock()
        mock_get_loop_client.return_value = mock_loop_client
        mock_loop_client.messages.create.return_value = AsyncMock(
            stop_reason="end_turn",
            content=[AsyncMock(text="Voice summary result", type="text")],
            usage=AsyncMock(input_tokens=100, output_tokens=50),
        )

        response = await client.post(
            "/api/agent/chat",
            json={
                "message": "summarize this",
                "voice_transcript": "This is the transcript of a voice message",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "voice_summary"
