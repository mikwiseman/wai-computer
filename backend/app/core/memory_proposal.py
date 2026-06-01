"""Governance lifecycle for memory proposals — the "auto + cherry-pick" gate.

Durable facts no longer flow straight into a user's memory blocks. They pass
through here first:

- **Auto-accept** when the change is *additive* (``append``) and the model is
  confident (``confidence >= AUTO_ACCEPT_CONFIDENCE``) from first-party
  material — applied immediately via the same ``write_block`` path the
  in-turn ``remember`` tool uses, so there is one audit trail.
- **Queue for review** when the change *overwrites* prior truth
  (``replace_line`` / ``rewrite`` → high risk), is low-confidence, or is a pure
  model inference. The user accepts or rejects with one tap.

Idempotency: each fact has a deterministic ``dedup_key``; a fact is proposed
once ever. A rejected fact is not re-proposed (a "no" is durable), and an
accepted fact is not re-proposed (it's already in memory). No fallbacks — a
failed auto-apply stays ``pending`` with the reason recorded, never silently
dropped.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import user_memory as user_memory_module
from app.models.memory_proposal import MemoryProposal

# Additive facts at/above this confidence auto-accept; everything else queues.
AUTO_ACCEPT_CONFIDENCE = 0.8

Decision = Literal["auto_accepted", "queued"]


def _normalize_for_dedup(text: str) -> str:
    """Collapse case + whitespace so trivially-different phrasings of the
    same fact share a dedup_key."""
    return " ".join((text or "").lower().split())


def stable_dedup_key(block_label: str, operation: str, content: str) -> str:
    payload = f"{block_label}\x00{operation}\x00{_normalize_for_dedup(content)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def risk_for_operation(operation: str) -> str:
    """append is additive (low risk); replace_line / rewrite overwrite prior
    truth (high risk) and always route to human review."""
    return "low" if operation == "append" else "high"


def is_auto_eligible(*, risk: str, confidence: float, authority: str) -> bool:
    """Auto-accept only additive, confident, non-speculative changes."""
    return (
        risk == "low"
        and confidence >= AUTO_ACCEPT_CONFIDENCE
        and authority != "model"
    )


@dataclass
class ProposalOutcome:
    proposal: MemoryProposal
    decision: Decision


async def _existing(
    db: AsyncSession, user_id: uuid.UUID, dedup_key: str
) -> MemoryProposal | None:
    stmt = select(MemoryProposal).where(
        MemoryProposal.user_id == user_id,
        MemoryProposal.dedup_key == dedup_key,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _apply_to_memory(
    db: AsyncSession,
    proposal: MemoryProposal,
    *,
    decided_by: Literal["auto", "user"],
) -> None:
    """Write the proposal's payload into the canonical memory block and mark
    it accepted. Raises user_memory.MemoryError if the write is rejected by
    block policy (char limit, replace_line target not found, …)."""
    source = "consolidator" if decided_by == "auto" else "user"
    await user_memory_module.write_block(
        db,
        proposal.user_id,
        label=proposal.block_label,
        operation=proposal.operation,
        content=proposal.content,
        target_line=proposal.target_line,
        source=source,
    )
    proposal.status = "accepted"
    proposal.decided_by = decided_by
    proposal.decided_at = datetime.now(timezone.utc)
    if decided_by == "auto":
        proposal.decision_reason = (
            f"auto: low-risk, confidence {proposal.confidence:.2f} "
            f">= {AUTO_ACCEPT_CONFIDENCE}"
        )


async def propose_block_update(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    block_label: str,
    operation: str,
    content: str,
    confidence: float,
    target_line: str | None = None,
    authority: str = "self",
    summary: str | None = None,
    evidence: list[Any] | None = None,
) -> ProposalOutcome | None:
    """Record a proposed memory change and decide auto-accept vs review.

    Returns the outcome, or ``None`` if this exact fact was already proposed
    (idempotent — never propose the same fact twice).
    """
    content = (content or "").strip()
    if not content:
        # An empty append/rewrite carries no fact — nothing to govern.
        return None

    dedup_key = stable_dedup_key(block_label, operation, content)
    if await _existing(db, user_id, dedup_key) is not None:
        return None

    risk = risk_for_operation(operation)
    proposal = MemoryProposal(
        user_id=user_id,
        kind="memory_upsert",
        risk=risk,
        block_label=block_label,
        operation=operation,
        content=content,
        target_line=target_line,
        summary=(summary or f"{operation} → {block_label}: {content}")[:500],
        confidence=float(confidence),
        authority=authority,
        evidence=evidence,
        dedup_key=dedup_key,
        status="pending",
    )
    db.add(proposal)
    await db.flush()

    if not is_auto_eligible(risk=risk, confidence=confidence, authority=authority):
        return ProposalOutcome(proposal=proposal, decision="queued")

    try:
        await _apply_to_memory(db, proposal, decided_by="auto")
    except user_memory_module.MemoryError as exc:
        # No silent drop: keep it pending with the reason so a human sees it.
        proposal.decision_reason = f"auto-apply failed, queued for review: {exc}"
        return ProposalOutcome(proposal=proposal, decision="queued")
    return ProposalOutcome(proposal=proposal, decision="auto_accepted")


async def list_proposals(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[MemoryProposal]:
    stmt = select(MemoryProposal).where(MemoryProposal.user_id == user_id)
    if status is not None:
        stmt = stmt.where(MemoryProposal.status == status)
    stmt = stmt.order_by(MemoryProposal.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def _load_pending(
    db: AsyncSession, user_id: uuid.UUID, proposal_id: uuid.UUID
) -> MemoryProposal:
    stmt = select(MemoryProposal).where(
        MemoryProposal.id == proposal_id,
        MemoryProposal.user_id == user_id,
    )
    proposal = (await db.execute(stmt)).scalar_one_or_none()
    if proposal is None:
        raise LookupError("proposal not found")
    if proposal.status != "pending":
        raise ValueError(f"proposal is already {proposal.status}")
    return proposal


async def accept_proposal(
    db: AsyncSession, user_id: uuid.UUID, proposal_id: uuid.UUID
) -> MemoryProposal:
    """Promote a pending proposal into canonical memory (one-tap review)."""
    proposal = await _load_pending(db, user_id, proposal_id)
    await _apply_to_memory(db, proposal, decided_by="user")
    proposal.decision_reason = "accepted in review"
    await db.flush()
    return proposal


async def reject_proposal(
    db: AsyncSession,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    reason: str | None = None,
) -> MemoryProposal:
    """Reject a pending proposal — durable, so it is never re-proposed."""
    proposal = await _load_pending(db, user_id, proposal_id)
    proposal.status = "rejected"
    proposal.decided_by = "user"
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decision_reason = reason or "rejected in review"
    await db.flush()
    return proposal
