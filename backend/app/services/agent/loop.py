"""Agent Loop — the core execution engine.

Flow:
1. Message arrives (voice/text from any interface)
2. Intent Router classifies the message
3. Model Router picks the right model
4. Soul Prompt assembled with user context
5. Agent executes with tool calling (max 10 turns)
6. Result returned to caller
"""

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.agent.router import Intent, classify_intent, get_model_for_intent
from app.services.agent.soul import build_soul_prompt

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_TURNS = 10
API_TIMEOUT = 120  # seconds
API_MAX_RETRIES = 3
API_RETRY_BASE_DELAY = 1.0  # seconds

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    """Return a cached AsyncAnthropic client."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=API_TIMEOUT,
        )
    return _client


async def _api_call_with_retry(client: anthropic.AsyncAnthropic, **kwargs) -> anthropic.types.Message:
    """Call Claude API with exponential backoff on transient errors."""
    for attempt in range(API_MAX_RETRIES):
        try:
            return await client.messages.create(**kwargs)
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            if attempt == API_MAX_RETRIES - 1:
                raise
            delay = API_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("Claude API error (attempt %d/%d): %s — retrying in %.1fs", attempt + 1, API_MAX_RETRIES, e, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Unreachable")


@dataclass
class AgentMessage:
    role: str  # "user" or "assistant"
    content: str


@dataclass
class AgentContext:
    user_id: UUID
    user_name: str | None = None
    user_language: str = "en"
    timezone: str = "UTC"
    connected_services: list[str] = field(default_factory=list)
    identity_memories: list[str] = field(default_factory=list)
    working_context: list[str] = field(default_factory=list)
    recalled_memories: list[str] = field(default_factory=list)
    conversation_history: list[AgentMessage] = field(default_factory=list)
    has_voice: bool = False
    voice_transcript: str | None = None
    db: AsyncSession | None = None


@dataclass
class AgentResult:
    response: str
    intent: Intent
    model_used: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0


TOOLS = [
    {
        "name": "search_recordings",
        "description": (
            "Search user's audio recordings and meeting transcripts by semantic meaning. "
            "Returns relevant transcript segments with speaker, recording title, and timestamps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "track_commitment",
        "description": "Track a promise or commitment detected in conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "who": {"type": "string", "description": "Who made the promise"},
                "what": {"type": "string", "description": "What was promised"},
                "deadline": {
                    "type": "string",
                    "description": "When it should be done (YYYY-MM-DD or description)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["i_promised", "they_promised"],
                    "description": "Whether user promised or someone else promised",
                },
            },
            "required": ["who", "what", "direction"],
        },
    },
    {
        "name": "extract_entities",
        "description": (
            "Extract people, topics, decisions, dates, and amounts from text. "
            "Use when the user shares meeting notes, voice transcripts, or complex messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to extract entities from"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_commitments",
        "description": (
            "List open commitments/promises. Shows what the user promised "
            "others and what others promised the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["all", "i_promised", "they_promised"],
                    "description": "Filter by direction. Default: all",
                },
            },
        },
    },
    {
        "name": "search_web",
        "description": "Search the internet for current information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
]


async def execute_tool(tool_name: str, tool_input: dict, context: AgentContext) -> str:
    """Execute a tool call and return the result as a string."""
    logger.info(f"Executing tool: {tool_name} for user {context.user_id}")

    if tool_name == "search_recordings":
        return await _tool_search_recordings(tool_input, context)
    elif tool_name == "track_commitment":
        return await _tool_track_commitment(tool_input, context)
    elif tool_name == "extract_entities":
        return _tool_extract_entities(tool_input)
    elif tool_name == "list_commitments":
        return await _tool_list_commitments(tool_input, context)
    elif tool_name == "search_web":
        from app.services.agent.web_search import search_web

        return await search_web(tool_input.get("query", ""))
    else:
        return f"Unknown tool: {tool_name}"


async def _tool_search_recordings(tool_input: dict, context: AgentContext) -> str:
    """Search recordings using wai-computer's hybrid RRF search."""
    from app.core.chat import build_context_text, retrieve_context

    query = tool_input.get("query", "")
    if not context.db:
        return "Database session not available."

    rows = await retrieve_context(context.db, context.user_id, query)
    if not rows:
        return f"No recordings found matching: {query}"
    return build_context_text(rows)


async def _tool_track_commitment(tool_input: dict, context: AgentContext) -> str:
    """Track a commitment."""
    from app.services.agent.commitments import (
        CommitmentData,
        CommitmentDirection,
        save_commitment,
    )

    who = tool_input.get("who", "Unknown")
    what = tool_input.get("what", "")
    deadline = tool_input.get("deadline")
    direction_str = tool_input.get("direction", "they_promised")

    direction = (
        CommitmentDirection.I_PROMISED
        if direction_str == "i_promised"
        else CommitmentDirection.THEY_PROMISED
    )

    commitment = CommitmentData(who=who, what=what, direction=direction, deadline=deadline)
    await save_commitment(commitment, context.user_id)

    deadline_text = f" by {deadline}" if deadline else ""
    if direction == CommitmentDirection.I_PROMISED:
        return f"Tracked: You promised {who} to {what}{deadline_text}"
    return f"Tracked: {who} promised to {what}{deadline_text}"


def _tool_extract_entities(tool_input: dict) -> str:
    """Extract entities from text using fast pattern matching."""
    from app.services.agent.entities import extract_entities_fast, format_entities_for_display

    text = tool_input.get("text", "")
    if not text:
        return "No text provided for entity extraction."
    entities = extract_entities_fast(text)
    return format_entities_for_display(entities)


async def _tool_list_commitments(tool_input: dict, context: AgentContext) -> str:
    """List user's open commitments from DB."""
    from app.services.agent.commitments import (
        CommitmentDirection,
        format_commitments_for_display,
        get_user_commitments,
    )

    direction_str = tool_input.get("direction", "all")
    if direction_str == "i_promised":
        direction = CommitmentDirection.I_PROMISED
    elif direction_str == "they_promised":
        direction = CommitmentDirection.THEY_PROMISED
    else:
        direction = None

    commitments = await get_user_commitments(context.user_id, direction=direction)
    return format_commitments_for_display(commitments)


async def run_agent(context: AgentContext, message: str) -> AgentResult:
    """Run the agent loop: classify -> route -> execute -> respond."""
    from app.services.agent.metrics import increment

    increment("agent_requests_total")
    intent = await classify_intent(message, has_voice=context.has_voice)
    model = get_model_for_intent(intent)
    increment(f"agent_intent_{intent.value}")

    logger.info(f"Agent: intent={intent.value}, model={model}, user={context.user_id}")

    system_prompt = build_soul_prompt(
        user_name=context.user_name,
        user_language=context.user_language,
        timezone=context.timezone,
        connected_services=context.connected_services,
        identity_memories=context.identity_memories,
        working_context=context.working_context,
        recalled_memories=context.recalled_memories,
    )

    messages = []
    for msg in context.conversation_history[-20:]:
        messages.append({"role": msg.role, "content": msg.content})

    user_content = message
    if context.voice_transcript:
        user_content = (
            f"[Voice message transcript]: {context.voice_transcript}\n\nUser's text: {message}"
            if message
            else f"[Voice message transcript]: {context.voice_transcript}"
        )

    messages.append({"role": "user", "content": user_content})

    client = _get_client()
    total_input_tokens = 0
    total_output_tokens = 0
    tool_call_count = 0

    try:
        for turn in range(MAX_TURNS):
            response = await _api_call_with_retry(
                client,
                model=model,
                max_tokens=settings.agent_max_turns * 400,
                system=system_prompt,
                messages=messages,
                tools=TOOLS,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            if response.stop_reason == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_blocks = [b for b in assistant_content if b.type == "tool_use"]
                tool_call_count += len(tool_blocks)

                async def _exec_tool(block):
                    try:
                        result = await execute_tool(block.name, block.input, context)
                    except Exception as e:
                        logger.error("Tool %s failed: %s", block.name, e)
                        result = f"Error executing {block.name}: {e}"
                    return {"type": "tool_result", "tool_use_id": block.id, "content": result}

                tool_results = await asyncio.gather(*[_exec_tool(b) for b in tool_blocks])

                messages.append({"role": "user", "content": list(tool_results)})
                continue

            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            if not text_parts:
                logger.warning("Agent response contained no text blocks (stop_reason=%s)", response.stop_reason)

            final_response = "\n".join(text_parts) if text_parts else "I processed your request but received no text response."

            return AgentResult(
                response=final_response,
                intent=intent,
                model_used=model,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                tool_calls=tool_call_count,
            )

        logger.warning("Agent reached MAX_TURNS=%d for user=%s", MAX_TURNS, context.user_id)
        return AgentResult(
            response="I've been working on this but reached my turn limit. Here's what I found so far.",
            intent=intent,
            model_used=model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            tool_calls=tool_call_count,
        )
    finally:
        increment("agent_tokens_input", total_input_tokens)
        increment("agent_tokens_output", total_output_tokens)
        increment("agent_tool_calls", tool_call_count)
