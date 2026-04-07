"""Commitment Tracking — never forget a promise.

Detects commitments in conversations:
- "I'll send..." -> user promised something
- "He said he'd..." -> someone promised user
- "Напишу до пятницы" -> Russian commitment detection

Stores in DB via wai-say's async session.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class CommitmentDirection(StrEnum):
    I_PROMISED = "i_promised"
    THEY_PROMISED = "they_promised"
    MUTUAL = "mutual"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


@dataclass
class CommitmentData:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    who: str = ""
    what: str = ""
    direction: CommitmentDirection = CommitmentDirection.THEY_PROMISED
    deadline: str | None = None
    status: CommitmentStatus = CommitmentStatus.OPEN
    source_context: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


I_PROMISED_PATTERNS = [
    r"(?:i'll|i will|i'm going to|let me|i can|i should|i need to|i have to)\s+(.{10,80})",
    r"(?:will do|on it|i'll handle|consider it done|leave it to me)",
    r"(?:я отправлю|я пришлю|я сделаю|я напишу|я позвоню|я подготовлю)\s*(.*)",
    r"(?:сделаю|напишу|отправлю|пришлю|позвоню|подготовлю)\s+(.{5,80})",
    r"(?:обещаю|договорились|беру на себя)",
]

THEY_PROMISED_PATTERNS = [
    r"(?:he'll|she'll|they'll|he will|she will|they will)\s+(.{10,80})",
    r"(\w+)\s+(?:said (?:he|she|they)'d|promised to|agreed to|committed to)\s+(.{10,80})",
    r"(\w+)\s+(?:will send|will do|will handle|will prepare|will call)\s*(.*)",
    r"(\w+)\s+(?:обещал[аи]?|сказал[аи]?\s+что)\s+(.{5,80})",
    r"(\w+)\s+(?:пришлёт|отправит|сделает|напишет|позвонит|подготовит)\s*(.*)",
]

DEADLINE_PATTERNS = [
    r"(?:by|before|until|no later than)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    r"(?:by|before|until)\s+(tomorrow|next week|end of (?:day|week|month))",
    r"(?:by|before|until|no later than)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)",
    r"(?:до|к|не позднее)\s+(понедельника|вторника|среды|четверга|пятницы|субботы|воскресенья)",
    r"(?:до|к)\s+(завтра|следующей недели|конца (?:дня|недели|месяца))",
    r"(?:до|к)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)",
]


def detect_commitments(text: str, user_name: str | None = None) -> list[CommitmentData]:
    """Detect commitments in a text message."""
    commitments = []
    lower = text.lower()

    for pattern in I_PROMISED_PATTERNS:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            what = (
                match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
            )
            deadline = _extract_deadline(text)
            commitments.append(
                CommitmentData(
                    who=user_name or "me",
                    what=what.strip()[:200],
                    direction=CommitmentDirection.I_PROMISED,
                    deadline=deadline,
                    source_context=text[:300],
                )
            )
            break

    for pattern in THEY_PROMISED_PATTERNS:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            who = match.group(1) if match.lastindex and match.lastindex >= 1 else "someone"
            what = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(0)
            deadline = _extract_deadline(text)
            commitments.append(
                CommitmentData(
                    who=who.strip().capitalize(),
                    what=what.strip()[:200],
                    direction=CommitmentDirection.THEY_PROMISED,
                    deadline=deadline,
                    source_context=text[:300],
                )
            )
            break

    return commitments


def _extract_deadline(text: str) -> str | None:
    """Extract deadline from text if present."""
    for pattern in DEADLINE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


async def save_commitment(commitment: CommitmentData, user_id: UUID) -> CommitmentData:
    """Persist a commitment to PostgreSQL."""
    from app.db.session import get_db_context
    from app.models.commitment import Commitment as CommitmentModel

    commitment.user_id = user_id
    async with get_db_context() as db:
        db_commitment = CommitmentModel(
            user_id=user_id,
            who=commitment.who,
            what=commitment.what,
            direction=commitment.direction.value,
            deadline=commitment.deadline,
            status=commitment.status.value,
            source_context=commitment.source_context,
        )
        db.add(db_commitment)
    logger.info(f"Commitment saved: {commitment.direction.value} - {commitment.who}: {commitment.what}")
    return commitment


async def get_user_commitments(
    user_id: UUID,
    direction: CommitmentDirection | None = None,
    status: CommitmentStatus = CommitmentStatus.OPEN,
) -> list[CommitmentData]:
    """Get commitments from DB."""
    from sqlalchemy import select

    from app.db.session import get_db_context
    from app.models.commitment import Commitment as CommitmentModel

    async with get_db_context() as db:
        query = select(CommitmentModel).where(
            CommitmentModel.user_id == user_id,
            CommitmentModel.status == status.value,
        )
        if direction:
            query = query.where(CommitmentModel.direction == direction.value)
        query = query.order_by(CommitmentModel.created_at.desc())
        result = await db.execute(query)
        rows = result.scalars().all()

        return [
            CommitmentData(
                id=row.id,
                user_id=row.user_id,
                who=row.who,
                what=row.what,
                direction=CommitmentDirection(row.direction),
                deadline=row.deadline,
                status=CommitmentStatus(row.status),
                source_context=row.source_context,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]


def format_commitments_for_display(commitments: list[CommitmentData]) -> str:
    """Format commitments as a readable string."""
    if not commitments:
        return "No open commitments found."

    lines = []
    i_promised = [c for c in commitments if c.direction == CommitmentDirection.I_PROMISED]
    they_promised = [c for c in commitments if c.direction == CommitmentDirection.THEY_PROMISED]

    if i_promised:
        lines.append("What you promised:")
        for c in i_promised:
            deadline_text = f" (by {c.deadline})" if c.deadline else ""
            lines.append(f"  - {c.what}{deadline_text}")

    if they_promised:
        lines.append("\nWhat others promised you:")
        for c in they_promised:
            deadline_text = f" (by {c.deadline})" if c.deadline else ""
            lines.append(f"  - {c.who}: {c.what}{deadline_text}")

    return "\n".join(lines)
