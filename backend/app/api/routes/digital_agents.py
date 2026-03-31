"""Digital agents routes — CRUD for autonomous AI agents."""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["digital-agents"])


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    schedule_type: str
    cron_expression: str | None
    status: str
    delivery_channel: str
    run_count: int
    error_count: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_result: str | None
    last_error: str | None
    created_at: datetime


class CreateAgentRequest(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


class UpdateAgentRequest(BaseModel):
    status: str | None = None  # active, paused


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: CreateAgentRequest, user: CurrentUser, db: Database,
) -> AgentResponse:
    """Create a digital agent from a natural language description."""
    from app.services.agent.digital_agents import create_agent_from_description

    logger.info("creating agent user_id=%s description_len=%d", user.id, len(request.description))
    try:
        agent = await create_agent_from_description(
            db=db, user_id=user.id, description=request.description,
        )
    except ValueError as e:
        logger.info("agent creation rejected user_id=%s reason=%s", user.id, str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    logger.info("agent created user_id=%s agent_id=%s name=%s", user.id, agent.id, agent.name)
    return _agent_to_response(agent)


@router.get("", response_model=list[AgentResponse])
async def list_agents(user: CurrentUser, db: Database) -> list[AgentResponse]:
    """List all agents for the current user."""
    from app.services.agent.digital_agents import list_user_agents

    agents = await list_user_agents(db, user.id)
    return [_agent_to_response(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: UUID, user: CurrentUser, db: Database) -> AgentResponse:
    """Get agent details including last result."""
    from app.services.agent.digital_agents import trigger_agent

    agent = await trigger_agent(db, user.id, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return _agent_to_response(agent)


@router.post("/{agent_id}/run", response_model=dict)
async def run_agent_now(agent_id: UUID, user: CurrentUser, db: Database) -> dict:
    """Manually trigger an agent execution."""
    from app.services.agent.digital_agents import trigger_agent

    agent = await trigger_agent(db, user.id, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    from app.tasks.agent_tasks import execute_agent

    execute_agent.delay(str(agent.id))
    return {"status": "dispatched", "agent_id": str(agent.id)}


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID, request: UpdateAgentRequest, user: CurrentUser, db: Database,
) -> AgentResponse:
    """Update agent status (pause/resume)."""
    from sqlalchemy import select

    from app.models.digital_agent import DigitalAgent

    result = await db.execute(
        select(DigitalAgent).where(
            DigitalAgent.id == agent_id, DigitalAgent.user_id == user.id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if request.status and request.status in ("active", "paused"):
        agent.status = request.status

    await db.flush()
    return _agent_to_response(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_route(agent_id: UUID, user: CurrentUser, db: Database) -> None:
    """Soft-delete an agent."""
    from app.services.agent.digital_agents import delete_agent

    deleted = await delete_agent(db, user.id, agent_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")


def _agent_to_response(agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        schedule_type=agent.schedule_type,
        cron_expression=agent.cron_expression,
        status=agent.status,
        delivery_channel=agent.delivery_channel,
        run_count=agent.run_count,
        error_count=agent.error_count,
        last_run_at=agent.last_run_at,
        next_run_at=agent.next_run_at,
        last_result=agent.last_result,
        last_error=agent.last_error,
        created_at=agent.created_at,
    )
