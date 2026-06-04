"""Durable journal for autonomous working-agents (P6).

Three tables on the existing Celery worker — no Temporal/LangGraph (unjustified
on a 3.8 GB box):

* ``agents`` — the agent DEFINITION: a job + how it wakes (cron | event |
  signal | chat) + its autonomy ceiling. v1 caps autonomy at ``propose`` — every
  unattended action queues for approval via the host gate.
* ``agent_runs`` — one execution. A stable ``trigger_key`` (UNIQUE) makes a
  redelivered wake RESUME the same run instead of forking a duplicate; ``status``
  + ``next_step_idx`` + ``heartbeat_at`` let any worker replay/resume after an
  OOM/SIGKILL (``recover_stuck_agent_runs``).
* ``agent_steps`` — the append-only journal: one row per replay boundary (plan /
  tool_call / tool_result / approval / verify / final). ``UNIQUE(run_id, idx)``
  orders it; a per-step ``idempotency_key`` makes every send/actuate
  effectively-once across replays.

Privacy: step/run payloads MAY carry recipient/body — they stay in Postgres only
and are NEVER logged raw (AGENTS.md). ``content_hash`` powers
skip-when-nothing-changed so an unchanged wake does no work.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Agent(Base, UUIDMixin, TimestampMixin):
    """An autonomous job definition: what to do + how it wakes."""

    __tablename__ = "agents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human label + the vertical the dispatcher routes on
    # (e.g. "commitments_friday_reminder" — the first vertical).
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    # How the agent wakes: cron | event | signal | chat.
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Cron expression / event filter / job params — the wake + behaviour bag.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # v1 autonomy ceiling: every unattended action queues for approval.
    autonomy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="propose"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Cron dispatch cursor (dispatch_due_agents: enabled & next_run_at <= now).
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last successful input fingerprint — skip a wake when nothing changed.
    content_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        # Serves dispatch_due_agents: WHERE trigger_type=? AND enabled AND next_run_at<=now.
        Index("ix_agents_due", "trigger_type", "enabled", "next_run_at"),
    )


class AgentRun(Base, UUIDMixin, TimestampMixin):
    """One execution of an agent — a replayable, resumable journal head."""

    __tablename__ = "agent_runs"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised so the guard/scoping needs no join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional orchestration edge: a parent run can spawn isolated child runs.
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        index=True,
    )
    parent_step_idx: Mapped[int | None] = mapped_column(Integer)
    # Optional chat origin: a chat turn can hand a long job to a durable
    # background run that reports its result back into this conversation. Both
    # SET NULL on delete so removing a chat/message never orphans the run row.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        index=True,
    )
    origin_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
    )
    # Stable per-wake key: a redelivered trigger RESUMES this run, never forks.
    trigger_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # pending | planning | running | awaiting_approval | done | failed | expired | skipped
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    # plan-then-execute plan + the done_spec the Haiku verifier checks + result.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    done_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # This run's input fingerprint (skip if unchanged from the agent's).
    content_hash: Mapped[str | None] = mapped_column(String(64))
    # The concrete wake payload: manual objective, event ids, webhook signal, etc.
    trigger_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(2000))
    # Replay cursor: the next journal index to execute.
    next_step_idx: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # Liveness for the OOM/SIGKILL backstop (recover_stuck_agent_runs).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("trigger_key", name="uq_agent_runs_trigger_key"),
        Index("ix_agent_runs_user_parent", "user_id", "parent_run_id"),
    )


class AgentStep(Base, UUIDMixin, TimestampMixin):
    """One append-only journal entry (a replay boundary) within a run."""

    __tablename__ = "agent_steps"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Monotonic position within the run; UNIQUE(run_id, idx) orders the journal.
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    # Journal-entry kind: plan, tool_call, tool_result, approval_request,
    # approval_result, verify, final, skip, cancel, error.
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # Durable content of this boundary (tool+args, result, verdict, ...).
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # Per-(run, step) effectively-once key for sends/actuates across replays.
    idempotency_key: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("run_id", "idx", name="uq_agent_steps_run_idx"),
    )
