"""Tests for the core agent execution loop."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agent.loop import (
    TOOLS,
    AgentContext,
    AgentResult,
    _tool_extract_entities,
    execute_tool,
    run_agent,
)
from app.services.agent.router import Intent


class TestToolDefinitions:
    def test_tools_list_has_seven_tools(self):
        assert len(TOOLS) == 7

    def test_tool_names(self):
        names = {t["name"] for t in TOOLS}
        assert names == {
            "search_recordings", "track_commitment", "extract_entities",
            "list_commitments", "search_web", "build_app", "build_site",
        }

    def test_each_tool_has_schema(self):
        for tool in TOOLS:
            assert "input_schema" in tool
            assert "description" in tool


class TestExtractEntities:
    def test_extracts_from_text(self):
        result = _tool_extract_entities({"text": "Alice decided to pay $500"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_text(self):
        result = _tool_extract_entities({"text": ""})
        assert "no text" in result.lower()

    def test_missing_text(self):
        result = _tool_extract_entities({})
        assert "no text" in result.lower()


class TestExecuteTool:
    async def test_unknown_tool(self):
        context = AgentContext(user_id=uuid4())
        result = await execute_tool("nonexistent_tool", {}, context)
        assert "unknown tool" in result.lower()

    async def test_search_web(self):
        mock_search = AsyncMock(return_value="Search results for AI")
        with patch("app.services.agent.web_search.search_web", mock_search):
            context = AgentContext(user_id=uuid4())
            result = await execute_tool("search_web", {"query": "AI news"}, context)
            assert result == "Search results for AI"
            mock_search.assert_called_once_with("AI news")


class TestRunAgent:
    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_run_agent_basic(self, mock_classify, mock_get_client):
        mock_classify.return_value = Intent.CHAT

        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(text="Hello there!", type="text")],
            usage=MagicMock(input_tokens=50, output_tokens=20),
        )

        context = AgentContext(user_id=uuid4(), user_name="Test")
        result = await run_agent(context, "hello")

        assert isinstance(result, AgentResult)
        assert result.response == "Hello there!"
        assert result.intent == Intent.CHAT
        assert result.tool_calls == 0

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_run_agent_with_voice(self, mock_classify, mock_get_client):
        mock_classify.return_value = Intent.VOICE_SUMMARY

        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(text="Voice summary here", type="text")],
            usage=MagicMock(input_tokens=100, output_tokens=50),
        )

        context = AgentContext(
            user_id=uuid4(),
            has_voice=True,
            voice_transcript="Hello this is a test",
        )
        result = await run_agent(context, "")

        assert result.intent == Intent.VOICE_SUMMARY

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_run_agent_respects_history(self, mock_classify, mock_get_client):
        from app.services.agent.loop import AgentMessage

        mock_classify.return_value = Intent.CHAT
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(text="I remember!", type="text")],
            usage=MagicMock(input_tokens=80, output_tokens=30),
        )

        context = AgentContext(
            user_id=uuid4(),
            conversation_history=[
                AgentMessage(role="user", content="My name is Mik"),
                AgentMessage(role="assistant", content="Nice to meet you, Mik!"),
            ],
        )
        await run_agent(context, "What is my name?")

        # Verify Claude was called with history + new message
        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert len(messages) == 3  # 2 history + 1 new


class TestAgentContext:
    def test_defaults(self):
        ctx = AgentContext(user_id=uuid4())
        assert ctx.user_language == "en"
        assert ctx.timezone == "UTC"
        assert ctx.has_voice is False
        assert ctx.voice_transcript is None
        assert ctx.db is None
        assert ctx.conversation_history == []
