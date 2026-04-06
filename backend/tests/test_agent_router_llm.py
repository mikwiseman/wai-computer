"""Tests for agent router LLM fallback classification."""

from unittest.mock import AsyncMock, patch

from app.services.agent.router import Intent, classify_intent


class TestLLMFallback:
    """Test LLM fallback classification for ambiguous messages."""

    @patch("app.services.agent.router.get_settings")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_llm_classifies_ambiguous_message(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"
        mock_settings.return_value.agent_model = "claude-haiku-4-5"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="search")]
        )

        result = await classify_intent("tell me about the budget meeting")
        assert result == Intent.SEARCH

    @patch("app.services.agent.router.get_settings")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_llm_returns_chat_for_unknown_intent(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"
        mock_settings.return_value.agent_model = "claude-haiku-4-5"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="something_invalid")]
        )

        result = await classify_intent("tell me about the budget meeting")
        assert result == Intent.CHAT

    @patch("app.services.agent.router.get_settings")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_llm_failure_defaults_to_chat(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"
        mock_settings.return_value.agent_model = "claude-haiku-4-5"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        result = await classify_intent("tell me about the budget meeting")
        assert result == Intent.CHAT

    @patch("app.services.agent.router.get_settings")
    @patch("app.services.agent.router.anthropic.AsyncAnthropic")
    async def test_llm_truncates_long_messages(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value.anthropic_api_key = "test-key"
        mock_settings.return_value.agent_model = "claude-haiku-4-5"

        mock_client = AsyncMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[AsyncMock(text="chat")]
        )

        long_message = "x" * 1000
        result = await classify_intent(long_message)
        assert result == Intent.CHAT

        # Verify message was truncated to 500 chars
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "x" * 500 in prompt
        assert "x" * 501 not in prompt


class TestEdgeCasePatterns:
    """Test edge cases in pattern matching."""

    async def test_empty_message_falls_through(self):
        """Empty-ish message should fall to LLM or default."""
        # Single space — no pattern match, goes to LLM fallback
        with patch("app.services.agent.router.get_settings") as mock_settings, \
             patch("app.services.agent.router.anthropic.AsyncAnthropic") as mock_cls:
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_settings.return_value.agent_model = "claude-haiku-4-5"
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = AsyncMock(
                content=[AsyncMock(text="chat")]
            )
            result = await classify_intent("hi")
            assert result == Intent.CHAT

    async def test_build_keyword_mid_sentence(self):
        assert await classify_intent("I want to build a website") == Intent.BUILD

    async def test_search_keyword_mid_sentence(self):
        assert await classify_intent("can you find my notes on Python?") == Intent.SEARCH

    async def test_edit_darker(self):
        assert await classify_intent("make the header darker") == Intent.EDIT

    async def test_edit_lighter(self):
        assert await classify_intent("lighter background please") == Intent.EDIT

    async def test_action_send_message(self):
        assert await classify_intent("send a message to the team") == Intent.ACTION

    async def test_digest_summary_of(self):
        assert await classify_intent("summary of last week") == Intent.DIGEST

    async def test_commitment_who_owes(self):
        assert await classify_intent("who owes me a response?") == Intent.SEARCH
