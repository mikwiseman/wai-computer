"""Celery tasks for executing digital agents on schedule.

The run_due_agents task checks every minute for agents whose next_run_at
has passed, and dispatches execute_agent for each one.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from celery import shared_task

from app.config import get_settings


def _run_async(coro):
    """Run async code in Celery worker without EventLoop conflicts.

    Celery fork workers inherit a closed event loop from the parent.
    Creating a fresh loop avoids 'Future attached to a different loop'.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


logger = logging.getLogger(__name__)
settings = get_settings()

MAX_TOOL_ROUNDS = 2

SEARCH_WEB_TOOL = {
    "name": "search_web",
    "description": (
        "Search the internet for current information. "
        "Use this to find news, facts, prices, events, or any real-time data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}


def _build_tools_for_agent(agent_tools: str) -> list[dict]:
    """Build Claude tools list based on agent's configured tools."""
    tools = []
    tool_names = [t.strip() for t in agent_tools.split(",") if t.strip()]
    if "search_web" in tool_names:
        tools.append(SEARCH_WEB_TOOL)
    return tools


async def _execute_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call from Claude and return the result string."""
    if tool_name == "search_web":
        from app.services.agent.web_search import search_web

        query = tool_input.get("query", "")
        return await search_web(query)

    return f"Unknown tool: {tool_name}"


@shared_task
def run_due_agents():
    """Find and execute all agents whose next_run_at <= now."""
    return _run_async(_run_due_agents())


async def _run_due_agents() -> dict:
    from sqlalchemy import select

    from app.db.session import get_db_context
    from app.models.digital_agent import DigitalAgent

    now = datetime.now(UTC)
    dispatched = 0

    async with get_db_context() as db:
        result = await db.execute(
            select(DigitalAgent).where(
                DigitalAgent.status == "active",
                DigitalAgent.next_run_at <= now,
                DigitalAgent.next_run_at.isnot(None),
            )
        )
        agents = result.scalars().all()

        for agent in agents:
            execute_agent.delay(str(agent.id))
            dispatched += 1

    return {"checked_at": now.isoformat(), "dispatched": dispatched}


@shared_task(
    bind=True,
    max_retries=2,
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
)
def execute_agent(self, agent_id: str):
    """Execute a single digital agent run."""
    return _run_async(_execute_agent(UUID(agent_id)))


async def _execute_agent(agent_id: UUID) -> dict:
    import anthropic
    from sqlalchemy import select

    from app.db.session import get_db_context
    from app.models.digital_agent import DigitalAgent
    from app.services.agent.loop import _get_client

    async with get_db_context() as db:
        result = await db.execute(
            select(DigitalAgent).where(DigitalAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent or agent.status != "active":
            return {"status": "skipped"}

        try:
            tools = _build_tools_for_agent(agent.tools or "")

            client = _get_client()
            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Execute your task now. "
                        f"Current time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}."
                    ),
                }
            ]

            create_kwargs: dict = {
                "model": settings.agent_model,
                "max_tokens": agent.max_tokens_per_run,
                "system": agent.system_prompt,
                "messages": messages,
            }
            if tools:
                create_kwargs["tools"] = tools

            output = ""
            for _round in range(MAX_TOOL_ROUNDS + 1):
                response = await client.messages.create(**create_kwargs)

                if response.stop_reason != "tool_use":
                    text_parts = []
                    for block in response.content:
                        if hasattr(block, "text"):
                            text_parts.append(block.text)
                    output = "\n".join(text_parts).strip() if text_parts else ""
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            tool_result = await _execute_tool_call(block.name, block.input)
                        except Exception as e:
                            logger.error(f"Agent tool {block.name} failed: {e}")
                            tool_result = f"Error: {e}"
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": tool_result[:4000],
                            }
                        )
                messages.append({"role": "user", "content": tool_results})
                create_kwargs["messages"] = messages

            # Store result (Phase 1: API-only delivery)
            agent.last_run_at = datetime.now(UTC)
            agent.run_count += 1
            agent.error_count = 0
            agent.last_result = output[:2000]
            agent.last_error = None

            # Compute next run
            if agent.cron_expression:
                from app.services.agent.digital_agents import compute_next_run

                agent.next_run_at = compute_next_run(agent.cron_expression)

            await db.commit()
            logger.info(
                f"Agent executed: {agent.name} (id={agent.id}, run_count={agent.run_count})"
            )
            return {"agent_id": str(agent_id), "status": "completed"}

        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
        ) as e:
            agent.error_count += 1
            agent.last_error = str(e)[:500]
            await db.commit()
            logger.warning("Agent transient error (will retry): %s - %s", agent.name, e)
            raise  # Celery retry_backoff handles retry scheduling

        except anthropic.APIStatusError as e:
            agent.error_count += 1
            agent.last_error = str(e)[:500]
            if e.status_code in (401, 403):
                agent.status = "failed"
                logger.error("Agent auth failure, disabled: %s (id=%s)", agent.name, agent.id)
            await db.commit()
            logger.error("Agent permanent API error: %s - %s", agent.name, e)
            return {"agent_id": str(agent_id), "status": "error", "error": str(e)[:500]}

        except Exception as e:
            agent.error_count += 1
            agent.last_error = str(e)[:500]
            if agent.error_count >= 10:
                agent.status = "failed"
                logger.error(
                    "Agent auto-disabled after 10 errors: %s (id=%s)", agent.name, agent.id
                )
            await db.commit()
            logger.error("Agent execution failed: %s - %s", agent.name, e)
            return {"agent_id": str(agent_id), "status": "error", "error": str(e)[:500]}
