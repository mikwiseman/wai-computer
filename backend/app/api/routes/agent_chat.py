"""Agent chat route — enhanced chat with intent routing and tool calling."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database
from app.config import get_settings

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str | None = None
    voice_transcript: str | None = None


class AgentChatResponse(BaseModel):
    response: str
    intent: str
    model_used: str
    session_id: str
    tool_calls: int
    input_tokens: int
    output_tokens: int


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    user: CurrentUser,
    db: Database,
) -> AgentChatResponse:
    """Send a message to the AI agent with tool calling capabilities."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service not configured",
        )

    from app.services.agent.conversation import add_message, get_history_for_agent
    from app.services.agent.language import detect_language
    from app.services.agent.loop import AgentContext, AgentMessage, run_agent

    session_id = request.session_id or str(uuid.uuid4())

    history = get_history_for_agent(user.id)
    conversation_history = [
        AgentMessage(role=msg["role"], content=msg["content"]) for msg in history
    ]

    detected_lang = detect_language(request.message)

    context = AgentContext(
        user_id=user.id,
        user_name=user.email.split("@")[0] if user.email else None,
        user_language=detected_lang,
        conversation_history=conversation_history,
        has_voice=request.voice_transcript is not None,
        voice_transcript=request.voice_transcript,
        db=db,
    )

    result = await run_agent(context, request.message)

    add_message(user.id, "user", request.message)
    add_message(user.id, "assistant", result.response)

    return AgentChatResponse(
        response=result.response,
        intent=result.intent.value,
        model_used=result.model_used,
        session_id=session_id,
        tool_calls=result.tool_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
