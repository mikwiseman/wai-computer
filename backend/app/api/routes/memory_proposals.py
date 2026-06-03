"""Memory-proposal review queue — the cherry-pick half of raw→valuable governance.

The nightly consolidator parks destructive corrections and low-confidence
guesses here as ``pending`` proposals. The user accepts (promote into canonical
memory) or rejects (durable "no") with one tap.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Database
from app.core import memory_proposal as gov
from app.core import user_memory as user_memory_module
from app.models.memory_proposal import MemoryProposal

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryProposalResponse(BaseModel):
    id: str
    kind: str
    risk: str
    block_label: str
    operation: str
    content: str
    target_line: str | None
    summary: str
    confidence: float
    authority: str
    status: str
    decision_reason: str | None
    created_at: str | None
    decided_at: str | None


class MemoryProposalsResponse(BaseModel):
    proposals: list[MemoryProposalResponse]
    pending_count: int


class RejectRequest(BaseModel):
    reason: str | None = None


def _to_response(p: MemoryProposal) -> MemoryProposalResponse:
    return MemoryProposalResponse(
        id=str(p.id),
        kind=p.kind,
        risk=p.risk,
        block_label=p.block_label,
        operation=p.operation,
        content=p.content,
        target_line=p.target_line,
        summary=p.summary,
        confidence=p.confidence,
        authority=p.authority,
        status=p.status,
        decision_reason=p.decision_reason,
        created_at=p.created_at.isoformat() if p.created_at else None,
        decided_at=p.decided_at.isoformat() if p.decided_at else None,
    )


async def _pending_count(db: Database, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(MemoryProposal)
            .where(
                MemoryProposal.user_id == user_id,
                MemoryProposal.status == "pending",
            )
        )
        or 0
    )


@router.get("/proposals", response_model=MemoryProposalsResponse)
async def list_memory_proposals(
    user: CurrentUser,
    db: Database,
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> MemoryProposalsResponse:
    """The review queue. Defaults to pending; pass ?status=accepted|rejected|all."""
    effective = None if status_filter in (None, "all") else status_filter
    proposals = await gov.list_proposals(db, user.id, status=effective, limit=limit)
    return MemoryProposalsResponse(
        proposals=[_to_response(p) for p in proposals],
        pending_count=await _pending_count(db, user.id),
    )


@router.post("/proposals/{proposal_id}/accept", response_model=MemoryProposalResponse)
async def accept_memory_proposal(
    proposal_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> MemoryProposalResponse:
    """Promote a pending proposal into canonical memory (one-tap accept)."""
    try:
        proposal = await gov.accept_proposal(db, user.id, proposal_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except user_memory_module.MemoryError as exc:
        # e.g. accepting a rewrite that overflows the block char_limit.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return _to_response(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=MemoryProposalResponse)
async def reject_memory_proposal(
    proposal_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
    body: RejectRequest | None = None,
) -> MemoryProposalResponse:
    """Reject a pending proposal — durable, so it is never re-proposed."""
    try:
        proposal = await gov.reject_proposal(
            db, user.id, proposal_id, reason=(body.reason if body else None)
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _to_response(proposal)
