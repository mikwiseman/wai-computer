"""Tests for the core agent execution loop."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anthropic

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
    def test_tools_list_has_five_tools(self):
        assert len(TOOLS) == 5

    def test_tool_names(self):
        names = {t["name"] for t in TOOLS}
        assert names == {
            "search_recordings", "track_commitment", "extract_entities",
            "list_commitments", "search_web",
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


class TestRunAgentToolCalling:
    """Test the agent loop when Claude invokes tools."""

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_tool_call_then_final_answer(self, mock_classify, mock_get_client):
        """Agent calls search_recordings, gets results, then responds with final text."""
        mock_classify.return_value = Intent.SEARCH
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        # First call: Claude requests tool_use
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "search_recordings"
        tool_use_block.input = {"query": "budget discussion"}
        tool_use_block.id = "tool_123"

        first_response = MagicMock(
            stop_reason="tool_use",
            content=[tool_use_block],
            usage=MagicMock(input_tokens=50, output_tokens=20),
        )

        # Second call: Claude gives final text answer
        text_block = MagicMock(type="text")
        text_block.text = "Based on the recordings, the budget was $5000."
        second_response = MagicMock(
            stop_reason="end_turn",
            content=[text_block],
            usage=MagicMock(input_tokens=100, output_tokens=40),
        )

        mock_client.messages.create.side_effect = [first_response, second_response]

        mock_db = AsyncMock()
        context = AgentContext(user_id=uuid4(), user_name="Test", db=mock_db)

        search_patch = "app.services.agent.loop._tool_search_recordings"
        with patch(search_patch, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = "Recording: Budget meeting - $5000"
            result = await run_agent(context, "what was the budget?")

        assert result.response == "Based on the recordings, the budget was $5000."
        assert result.intent == Intent.SEARCH
        assert result.tool_calls == 1
        assert result.input_tokens == 150
        assert result.output_tokens == 60

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_max_turns_reached(self, mock_classify, mock_get_client):
        """Agent hits MAX_TURNS limit and returns fallback message."""
        mock_classify.return_value = Intent.SEARCH
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        # Every response requests another tool call
        tool_block = MagicMock(
            type="tool_use", name="search_recordings",
            input={"query": "x"}, id="t1",
        )
        tool_response = MagicMock(
            stop_reason="tool_use",
            content=[tool_block],
            usage=MagicMock(input_tokens=10, output_tokens=5),
        )
        mock_client.messages.create.return_value = tool_response

        context = AgentContext(user_id=uuid4(), db=AsyncMock())

        search_patch = "app.services.agent.loop._tool_search_recordings"
        with patch(search_patch, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = "No results"
            result = await run_agent(context, "find something")

        assert "turn limit" in result.response.lower() or "limit" in result.response.lower()
        assert result.tool_calls == 10  # MAX_TURNS

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_no_text_blocks_in_response(self, mock_classify, mock_get_client):
        """Agent returns response even when Claude sends no text blocks."""
        mock_classify.return_value = Intent.CHAT
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        empty_response = MagicMock(
            stop_reason="end_turn",
            content=[],  # No text blocks
            usage=MagicMock(input_tokens=20, output_tokens=0),
        )
        mock_client.messages.create.return_value = empty_response

        context = AgentContext(user_id=uuid4())
        result = await run_agent(context, "hello")

        assert "no text response" in result.response.lower()

    @patch("app.services.agent.loop._get_client")
    @patch("app.services.agent.loop.classify_intent")
    async def test_tool_execution_error_handled(self, mock_classify, mock_get_client):
        """Agent continues when a tool raises an exception."""
        mock_classify.return_value = Intent.SEARCH
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        tool_block = MagicMock(
            type="tool_use", name="search_recordings",
            input={"query": "test"}, id="t1",
        )
        first_response = MagicMock(
            stop_reason="tool_use",
            content=[tool_block],
            usage=MagicMock(input_tokens=30, output_tokens=10),
        )

        text_block = MagicMock(type="text")
        text_block.text = "Sorry, I couldn't find that."
        second_response = MagicMock(
            stop_reason="end_turn",
            content=[text_block],
            usage=MagicMock(input_tokens=50, output_tokens=20),
        )
        mock_client.messages.create.side_effect = [first_response, second_response]

        context = AgentContext(user_id=uuid4(), db=AsyncMock())

        search_patch = "app.services.agent.loop._tool_search_recordings"
        with patch(search_patch, new_callable=AsyncMock) as mock_search:
            mock_search.side_effect = RuntimeError("DB connection failed")
            result = await run_agent(context, "find meeting notes")

        assert result.response == "Sorry, I couldn't find that."
        assert result.tool_calls == 1


class TestExecuteToolCoverage:
    """Additional execute_tool coverage for tool dispatch."""

    async def test_search_recordings_no_db(self):
        context = AgentContext(user_id=uuid4(), db=None)
        result = await execute_tool("search_recordings", {"query": "test"}, context)
        assert "not available" in result.lower()

    async def test_search_recordings_with_results(self):
        context = AgentContext(user_id=uuid4(), db=AsyncMock())
        p = "app.services.agent.loop._tool_search_recordings"
        with patch(p, new_callable=AsyncMock) as mock:
            mock.return_value = "Found: Budget meeting transcript"
            result = await execute_tool(
                "search_recordings", {"query": "budget"}, context,
            )
        assert "budget" in result.lower()

    async def test_track_commitment(self):
        context = AgentContext(user_id=uuid4())
        p = "app.services.agent.loop._tool_track_commitment"
        with patch(p, new_callable=AsyncMock) as mock:
            mock.return_value = "Tracked: You promised Alice to send report"
            result = await execute_tool(
                "track_commitment",
                {"who": "Alice", "what": "send report",
                 "direction": "i_promised"},
                context,
            )
        assert "tracked" in result.lower()

    async def test_list_commitments(self):
        context = AgentContext(user_id=uuid4())
        p = "app.services.agent.loop._tool_list_commitments"
        with patch(p, new_callable=AsyncMock) as mock:
            mock.return_value = "No open commitments."
            result = await execute_tool(
                "list_commitments", {"direction": "all"}, context,
            )
        assert "commitments" in result.lower()

    async def test_extract_entities_via_dispatch(self):
        context = AgentContext(user_id=uuid4())
        result = await execute_tool(
            "extract_entities",
            {"text": "Alice decided to pay $500 by Friday"},
            context,
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestApiRetry:
    """Test _api_call_with_retry behavior."""

    async def test_succeeds_on_first_try(self):
        from app.services.agent.loop import _api_call_with_retry

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_client.messages.create.return_value = mock_response

        result = await _api_call_with_retry(mock_client, model="test", max_tokens=100, messages=[])
        assert result == mock_response
        assert mock_client.messages.create.call_count == 1

    @patch("app.services.agent.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep):
        from app.services.agent.loop import _api_call_with_retry

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_client.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={"error": {"message": "rate limited", "type": "rate_limit_error"}},
            ),
            mock_response,
        ]

        result = await _api_call_with_retry(mock_client, model="test", max_tokens=100, messages=[])
        assert result == mock_response
        assert mock_client.messages.create.call_count == 2
        mock_sleep.assert_called_once()

    @patch("app.services.agent.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_after_max_retries(self, mock_sleep):
        import pytest

        from app.services.agent.loop import _api_call_with_retry

        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body={"error": {"message": "rate limited", "type": "rate_limit_error"}},
        )

        with pytest.raises(anthropic.RateLimitError):
            await _api_call_with_retry(mock_client, model="test", max_tokens=100, messages=[])

        assert mock_client.messages.create.call_count == 3  # API_MAX_RETRIES


class TestAgentContext:
    def test_defaults(self):
        ctx = AgentContext(user_id=uuid4())
        assert ctx.user_language == "en"
        assert ctx.timezone == "UTC"
        assert ctx.has_voice is False
        assert ctx.voice_transcript is None
        assert ctx.db is None
        assert ctx.conversation_history == []
