"""Built-in Wai agent sessions.

This module is the bridge between the existing companion conversation table and
the durable agent journal. Normal Wai usage creates ``AgentRun`` rows tied to a
conversation, so Mac/Web/Telegram can render a Hermes-style task timeline while
preserving Wai's recordings, materials, memory, reminders, and approval gates.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_runtime import (
    AgentPlan,
    execute_agent_step,
    run_job,
    static_config_planner,
)
from app.core.companion import COMPANION_AUTO_TITLE_MAX_CHARS, _auto_title_from_user_request
from app.models.agent import Agent, AgentRun
from app.models.companion import ChatMessage, Conversation

WAI_AGENT_NAME = "Wai"
WAI_AGENT_KIND = "wai"
WAI_AGENT_TRIGGER_TYPE = "chat"
WAI_SESSION_SCOPE_KIND = "wai_session"

_BUILD_WEB_RE = re.compile(
    r"\b(build|create|make|generate)\b.*\b(web\s?page|landing|html|site|website)\b",
    re.IGNORECASE,
)
_UNAVAILABLE_RE = re.compile(
    r"\b(shell|terminal|bash|zsh|run command|execute command|ssh|docker)\b",
    re.IGNORECASE,
)
_SEND_TELEGRAM_RE = re.compile(
    r"^(?:send|отправь|отправить|напиши|написать)\s+(?:message\s+)?(?P<text>.+)$",
    re.IGNORECASE,
)
_BRAIN_MAP_RE = re.compile(
    r"\b(map|diagram|canvas|schema|scheme|timeline|relationship|graph|mirror|miro)\b"
    r"|(?:карта|карту|схема|схему|диаграмма|диаграмму|хронология|хронологию|связи|зеркало)",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_title(text: str) -> str:
    title = _auto_title_from_user_request(text)
    return title[:COMPANION_AUTO_TITLE_MAX_CHARS].strip() or WAI_AGENT_NAME


def _context_from_payload(run: AgentRun) -> dict[str, Any] | None:
    payload = run.trigger_payload or {}
    context = payload.get("context")
    return context if isinstance(context, dict) else None


def _objective_from_payload(run: AgentRun) -> str:
    payload = run.trigger_payload or {}
    objective = str(payload.get("objective") or "").strip()
    return objective or "Continue"


def _is_cyrillic(text: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)


def _agent_text(language_source: str, english: str, russian: str) -> str:
    return russian if _is_cyrillic(language_source) else english


def _brain_map_source_scope(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not context:
        return None
    ref_type = str(context.get("ref_type") or "").strip()
    ref_id = str(context.get("ref_id") or "").strip()
    if ref_type not in {"recording", "item", "chat"} or not ref_id:
        return None
    return {"sources": [{"source_kind": ref_type, "source_id": ref_id}]}


def _html_artifact_for_objective(objective: str) -> str:
    title = _normalize_title(objective)
    escaped_title = html.escape(title)
    escaped_objective = html.escape(objective)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f1411;
      color: #f4f1e8;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 20% 10%, #3f513f 0, transparent 26rem),
        #0f1411;
    }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 72px 28px; }}
    header {{ min-height: 68vh; display: grid; align-content: center; gap: 24px; }}
    h1 {{ font-size: clamp(44px, 7vw, 92px); line-height: .94; margin: 0; letter-spacing: 0; }}
    p {{ color: #cfc8b6; font-size: 20px; line-height: 1.55; max-width: 720px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .card {{
      border: 1px solid rgb(255 255 255 / 12%);
      border-radius: 8px;
      padding: 20px;
      background: rgb(255 255 255 / 6%);
    }}
    .label {{ color: #f3a047; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="label">Wai artifact</div>
      <h1>{escaped_title}</h1>
      <p>{escaped_objective}</p>
    </header>
    <section class="grid" aria-label="Page sections">
      <article class="card">
        <h2>Concept</h2>
        <p>Clear first-screen message, fast scanning, and responsive layout.</p>
      </article>
      <article class="card">
        <h2>Program</h2>
        <p>Tracks, schedule, speakers, judging, and submission details can be filled in here.</p>
      </article>
      <article class="card">
        <h2>Action</h2>
        <p>Add registration, contact, or waitlist behavior when the destination is ready.</p>
      </article>
    </section>
  </main>
</body>
</html>
"""


async def ensure_wai_agent(db: AsyncSession, user_id: UUID) -> Agent:
    existing = (
        await db.execute(
            select(Agent)
            .where(
                Agent.user_id == user_id,
                Agent.kind == WAI_AGENT_KIND,
                Agent.name == WAI_AGENT_NAME,
            )
            .order_by(Agent.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.enabled:
            existing.enabled = True
        return existing

    agent = Agent(
        user_id=user_id,
        name=WAI_AGENT_NAME,
        kind=WAI_AGENT_KIND,
        trigger_type=WAI_AGENT_TRIGGER_TYPE,
        config={"runtime": "wai_builtin"},
        autonomy="propose",
        enabled=True,
    )
    db.add(agent)
    await db.flush()
    return agent


async def ensure_wai_session(
    db: AsyncSession,
    user_id: UUID,
    *,
    conversation_id: UUID | None = None,
    title: str | None = None,
    context: dict[str, Any] | None = None,
) -> Conversation:
    if conversation_id is not None:
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise ValueError("Wai session not found")
        if context:
            scope = dict(conversation.scope or {})
            scope["active_context"] = context
            conversation.scope = scope
        return conversation

    scope: dict[str, Any] = {"kind": WAI_SESSION_SCOPE_KIND}
    if context:
        scope["active_context"] = context
    conversation = Conversation(
        user_id=user_id,
        title=title,
        scope=scope,
        last_message_at=_now(),
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def start_wai_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    objective: str,
    conversation_id: UUID | None = None,
    context: dict[str, Any] | None = None,
    trigger_kind: str = "chat",
    idempotency_key: str | None = None,
) -> tuple[Conversation, AgentRun, bool]:
    objective = objective.strip()
    if not objective:
        raise ValueError("Wai task objective is required")
    conversation = await ensure_wai_session(
        db,
        user_id,
        conversation_id=conversation_id,
        title=_normalize_title(objective),
        context=context,
    )
    agent = await ensure_wai_agent(db, user_id)
    key = idempotency_key or uuid4().hex
    trigger_key = f"wai:{conversation.id}:{key}"
    existing = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user_id,
                AgentRun.trigger_key == trigger_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return conversation, existing, False

    if not (conversation.title or "").strip() or conversation.title == WAI_AGENT_NAME:
        conversation.title = _normalize_title(objective)
    conversation.last_message_at = _now()
    user_msg = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=objective,
    )
    db.add(user_msg)
    await db.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user_id,
        conversation_id=conversation.id,
        trigger_key=trigger_key,
        trigger_kind=trigger_kind,
        trigger_payload={
            "objective": objective,
            "context": context or {},
            "user_message_id": str(user_msg.id),
        },
    )
    db.add(run)
    await db.flush()
    return conversation, run, True


async def wai_task_planner(agent: Agent, run: AgentRun) -> AgentPlan:
    objective = _objective_from_payload(run)
    context = _context_from_payload(run)
    steps: list[dict[str, Any]] = [
        {"tool": "note", "args": {"text": f"Task: {objective}"}}
    ]

    if _UNAVAILABLE_RE.search(objective):
        steps.append(
            {
                "tool": "missing_capability",
                "args": {
                    "capability": "local.shell",
                    "reason": (
                        "Shell/terminal execution is not enabled until the local "
                        "gateway policy, approvals, redaction, and rollback flow exist."
                    ),
                },
            }
        )
    elif send_match := _SEND_TELEGRAM_RE.match(objective):
        message_text = send_match.group("text").strip()
        steps.append(
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "send_message_telegram",
                    "action_args": {"text": message_text},
                    "preview": f"Send a Telegram message to you: {message_text}",
                    "kind": "send",
                    "recipient_display": "you",
                },
            }
        )
    elif _BRAIN_MAP_RE.search(objective):
        title = _normalize_title(objective)
        args: dict[str, Any] = {"prompt": objective, "title": title}
        source_scope = _brain_map_source_scope(context)
        if source_scope is not None:
            args["source_scope"] = source_scope
        steps.extend(
            [
                {"tool": "create_brain_map", "args": args},
                {
                    "tool": "respond",
                    "args": {
                        "text": _agent_text(
                            objective,
                            (
                                f"Created a draft Brain Map for “{title}”. "
                                "Open Brain to inspect, refresh, or keep it."
                            ),
                            (
                                f"Создал черновик Brain Map «{title}». "
                                "Откройте Мозг, чтобы проверить, обновить или сохранить его."
                            ),
                        )
                    },
                },
            ]
        )
    elif context and context.get("ref_type") and context.get("ref_id"):
        args = {
            "ref_type": str(context["ref_type"]),
            "ref_id": str(context["ref_id"]),
            "objective": objective,
        }
        steps.extend(
            [
                {"tool": "load_context", "args": args},
                {"tool": "respond_from_context", "args": args},
            ]
        )
    elif _BUILD_WEB_RE.search(objective):
        title = _normalize_title(objective)
        steps.extend(
            [
                {
                    "tool": "create_artifact",
                    "args": {
                        "title": title,
                        "kind": "html",
                        "body": _html_artifact_for_objective(objective),
                        "filename": "index.html",
                        "mime_type": "text/html",
                        "preview_kind": "html",
                    },
                },
                {
                    "tool": "respond",
                    "args": {
                        "text": (
                            f"Created an HTML artifact for “{title}”. Open the artifact "
                            "preview instead of copying code from the chat."
                        )
                    },
                },
            ]
        )
    else:
        steps.append({"tool": "ask_brain", "args": {"question": objective, "limit": 12}})

    return AgentPlan(
        plan={"runtime": "wai_builtin", "steps": steps},
        done_spec={"mode": "all_steps_completed", "step_count": len(steps)},
    )


def planner_for_agent(agent: Agent):
    if agent.kind == WAI_AGENT_KIND or (agent.config or {}).get("runtime") == "wai_builtin":
        return wai_task_planner
    return static_config_planner


async def run_wai_run_inline(db: AsyncSession, run: AgentRun) -> AgentRun:
    return await run_job(
        db,
        run.id,
        planner=wai_task_planner,
        executor=execute_agent_step,
    )
