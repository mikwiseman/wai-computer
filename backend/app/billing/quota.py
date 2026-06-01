"""Word quota enforcement for free-tier weekly cap.

Week boundary: Sunday 00:00 UTC (matches Whispr Flow's reset cadence).
Quota record + check are atomic via PostgreSQL UPSERT on
``(user_id, week_start_utc)``.

NOTE — this is MONETIZATION accounting (a free-tier word cap gated by
``billing_enforcement_enabled``), NOT the Deepgram spend/abuse guard. Deepgram
COST control lives in ``app.core.transcription_guard`` (kill-switch, per-user +
global daily audio-minute ceilings, stream concurrency, circuit breaker), which
is enforced pre-flight on every billing path independently of this module and of
``billing_enforcement_enabled``. Do not mistake this word quota for a spend cap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.subscriptions import subscription_is_entitled
from app.config import get_settings
from app.models.billing import Plan, Subscription, UsageWeek
from app.models.recording import Recording
from app.models.user import User

# Whitespace tokenizer — close enough to "words" for billing purposes.
_WORD_TOKEN_RE: Final = re.compile(r"\S+")


def count_words(text: str | None) -> int:
    """Count whitespace-delimited tokens. Empty/None returns 0."""
    if not text:
        return 0
    return sum(1 for _ in _WORD_TOKEN_RE.finditer(text))


def current_week_start(now: datetime | None = None) -> date:
    """Return the Sunday 00:00 UTC anchor for the week containing ``now``.

    Python's ``weekday()`` returns Monday=0..Sunday=6; we want Sunday as the
    week start.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days_since_sunday = (now.weekday() + 1) % 7  # Mon=1, Sun=0
    return (now.date() - timedelta(days=days_since_sunday))


def next_week_start(now: datetime | None = None) -> datetime:
    """Return the next Sunday 00:00 UTC (the reset moment)."""
    sunday = current_week_start(now)
    return datetime.combine(sunday + timedelta(days=7), time.min, tzinfo=timezone.utc)


@dataclass(frozen=True)
class QuotaCheckResult:
    """Result of a pre-flight quota check."""

    allowed: bool
    words_used: int
    words_cap: int | None  # None means cap enforcement is disabled for this request.
    reset_at: datetime

    @property
    def cap_exceeded(self) -> bool:
        return not self.allowed


class QuotaExceededError(Exception):
    """Raised by ``WordQuota.record`` when the post-write total breaches the cap."""

    def __init__(self, result: QuotaCheckResult) -> None:
        self.result = result
        super().__init__(
            f"Word quota exceeded: {result.words_used}/{result.words_cap}"
        )


# Backwards-compatible alias for any external importers.
QuotaExceeded = QuotaExceededError


class WordQuota:
    """Per-user weekly transcribed-words quota.

    Usage:
        # Pre-flight check (advisory — caller decides):
        check = await WordQuota.check(db, user, estimated_words=600)
        if not check.allowed:
            raise HTTPException(402, ...)

        # Post-transcription recording (authoritative):
        await WordQuota.record(db, user, words=actual_word_count)
    """

    @staticmethod
    async def _resolve_plan_for_user_id(db: AsyncSession, user_id) -> Plan:
        """Resolve the user's effective plan (active subscription or free)."""
        current_subscription_id = (
            await db.execute(
                select(User.current_subscription_id).where(User.id == user_id)
            )
        ).scalar_one_or_none()
        if current_subscription_id is not None:
            sub = (
                await db.execute(
                    select(Subscription).where(Subscription.id == current_subscription_id)
                )
            ).scalar_one_or_none()
            if sub is not None and subscription_is_entitled(sub):
                plan = (
                    await db.execute(select(Plan).where(Plan.id == sub.plan_id))
                ).scalar_one_or_none()
                if plan is not None:
                    return plan
        # Fallback to the free plan row.
        plan = (
            await db.execute(select(Plan).where(Plan.code == "free"))
        ).scalar_one_or_none()
        if plan is None:
            raise RuntimeError("Free plan row missing — seed migration not applied?")
        return plan

    @classmethod
    async def _resolve_plan(cls, db: AsyncSession, user: User) -> Plan:
        return await cls._resolve_plan_for_user_id(db, user.id)

    @staticmethod
    async def _current_usage(db: AsyncSession, user_id, week_start: date) -> int:
        row = (
            await db.execute(
                select(UsageWeek.words_used).where(
                    UsageWeek.user_id == user_id,
                    UsageWeek.week_start_utc == week_start,
                )
            )
        ).scalar_one_or_none()
        return int(row or 0)

    @classmethod
    async def check(
        cls,
        db: AsyncSession,
        user: User,
        estimated_words: int = 0,
        *,
        now: datetime | None = None,
        enforce_override: bool = False,
    ) -> QuotaCheckResult:
        """Pre-flight check — does ``user`` have headroom for ``estimated_words``?

        Returns a QuotaCheckResult; caller decides what to do on a miss.

        Enforcement requires either the global ``billing_enforcement_enabled``
        env flag, or a per-request ``enforce_override`` (typically supplied
        by a tester flipping Payment mode on in their Mac client). When
        neither is set, every account is treated as uncapped — keeping v1.0
        free-for-everyone as the default while still letting individual
        testers run the real cap flow.
        """
        plan = await cls._resolve_plan(db, user)
        week_start = current_week_start(now)
        reset_at = next_week_start(now)

        settings = get_settings()
        if not (settings.billing_enforcement_enabled or enforce_override):
            used = await cls._current_usage(db, user.id, week_start)
            return QuotaCheckResult(
                allowed=True, words_used=used, words_cap=None, reset_at=reset_at
            )

        if plan.word_cap_per_week is None:
            return QuotaCheckResult(
                allowed=True, words_used=0, words_cap=None, reset_at=reset_at
            )

        used = await cls._current_usage(db, user.id, week_start)
        cap = plan.word_cap_per_week
        allowed = (used + max(estimated_words, 0)) <= cap
        return QuotaCheckResult(
            allowed=allowed, words_used=used, words_cap=cap, reset_at=reset_at
        )

    @classmethod
    async def record(
        cls,
        db: AsyncSession,
        user: User,
        words: int,
        *,
        now: datetime | None = None,
    ) -> QuotaCheckResult:
        return await cls.record_for_user_id(db, user.id, words=words, now=now)

    @classmethod
    async def record_for_user_id(
        cls,
        db: AsyncSession,
        user_id,
        words: int,
        *,
        now: datetime | None = None,
    ) -> QuotaCheckResult:
        """Atomically increment the user's weekly counter and return the new state.

        Always records — quota enforcement happens via ``check`` before the
        work starts; this method's job is to keep the ledger honest. The
        returned result reflects the *post-increment* total, which the caller
        can surface to the client.
        """
        if words < 0:
            words = 0
        plan = await cls._resolve_plan_for_user_id(db, user_id)
        week_start = current_week_start(now)
        reset_at = next_week_start(now)

        stmt = (
            pg_insert(UsageWeek)
            .values(user_id=user_id, week_start_utc=week_start, words_used=words)
            .on_conflict_do_update(
                constraint="uq_billing_usage_user_week",
                set_={"words_used": UsageWeek.words_used + words},
            )
            .returning(UsageWeek.words_used)
        )
        result = await db.execute(stmt)
        new_total = int(result.scalar_one())
        await db.flush()

        cap = plan.word_cap_per_week
        allowed = cap is None or new_total <= cap
        return QuotaCheckResult(
            allowed=allowed, words_used=new_total, words_cap=cap, reset_at=reset_at
        )


async def record_recording_transcript_words(
    db: AsyncSession,
    recording: Recording,
    transcript_text: str,
) -> QuotaCheckResult | None:
    """Record only the newly observed word delta for a recording transcript.

    Recording transcript saves can be retried or replaced. The billing ledger is
    append-only, so each recording stores the largest transcript word count that
    has already been billed and only increments the weekly usage by the delta.
    """
    actual_words = count_words(transcript_text)
    previous_words = max(recording.billed_word_count or 0, 0)
    if actual_words <= previous_words:
        return None
    recorded = await WordQuota.record_for_user_id(
        db,
        recording.user_id,
        words=actual_words - previous_words,
    )
    recording.billed_word_count = actual_words
    return recorded
