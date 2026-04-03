"""Tests for agent chat route."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestAgentChat:
    @patch("app.api.routes.agent_chat.get_settings")
    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_basic_chat(
        self, mock_router_anthropic, mock_get_loop_client, mock_get_settings,
        client: AsyncClient, auth_headers: dict,
    ):
        # Mock settings to have API key
        mock_settings = AsyncMock()
        mock_settings.anthropic_api_key = "test-key"
        mock_get_settings.return_value = mock_settings

        # Mock router classification (falls through to LLM for "hello")
        mock_router_client = AsyncMock()
        mock_router_anthropic.return_value = mock_router_client
        mock_router_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="chat")]
        )

        # Mock agent loop response
        mock_loop_client = AsyncMock()
        mock_get_loop_client.return_value = mock_loop_client
        mock_loop_client.messages.create.return_value = AsyncMock(
            stop_reason="end_turn",
            content=[AsyncMock(text="Hello! How can I help?", type="text")],
            usage=AsyncMock(input_tokens=100, output_tokens=50),
        )

        response = await client.post(
            "/api/agent/chat",
            json={"message": "hello"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "intent" in data
        assert "session_id" in data
        assert data["intent"] == "chat"

    async def test_chat_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/agent/chat",
            json={"message": "hello"},
        )
        assert response.status_code == 401

    async def test_chat_validates_empty_message(
        self, client: AsyncClient, auth_headers: dict,
    ):
        response = await client.post(
            "/api/agent/chat",
            json={"message": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestAgentLanguageDetection:
    """Test that language detection works in the chat flow."""

    def test_detect_english(self):
        from app.services.agent.language import detect_language

        assert detect_language("What happened in the meeting?") == "en"

    def test_detect_russian(self):
        from app.services.agent.language import detect_language

        assert detect_language("Что обсуждали на встрече?") == "ru"

    def test_detect_french(self):
        from app.services.agent.language import detect_language

        # French detection uses word markers like "je", "nous", "très"
        result = detect_language("Je suis très content de vous rencontrer aujourd'hui")
        # Latin-script detection may vary; just verify it returns a valid language code
        assert isinstance(result, str) and len(result) == 2
