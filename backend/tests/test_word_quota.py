"""Unit tests for the weekly word-quota service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.billing.quota import WordQuota, count_words, current_week_start, next_week_start
from app.models.billing import Plan, Subscription, UsageWeek
from app.models.user import User


def test_count_words_simple():
    assert count_words("hello world") == 2
    assert count_words("  hello   world  ") == 2
    assert count_words("") == 0
    assert count_words(None) == 0
    assert count_words("привет, мир!") == 2
    assert count_words("one") == 1


def test_count_words_unicode_punctuation():
    # Whitespace-delimited counting, not language-aware tokenization.
    assert count_words("don't stop") == 2
    assert count_words("AI/ML 2026") == 2  # "AI/ML" is one token


def test_current_week_start_for_sunday():
    # Sunday 2026-05-17 12:34:56 UTC -> week_start = 2026-05-17.
    sun = datetime(2026, 5, 17, 12, 34, 56, tzinfo=timezone.utc)
    assert current_week_start(sun).isoformat() == "2026-05-17"


def test_current_week_start_for_midweek():
    # Wednesday 2026-05-20 -> week started Sunday 2026-05-17.
    wed = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    assert current_week_start(wed).isoformat() == "2026-05-17"


def test_current_week_start_for_saturday():
    # Saturday 2026-05-23 -> still week of 2026-05-17.
    sat = datetime(2026, 5, 23, 23, 59, 59, tzinfo=timezone.utc)
    assert current_week_start(sat).isoformat() == "2026-05-17"


def test_next_week_start_is_following_sunday():
    wed = datetime(2026, 5, 20, 13, 0, 0, tzinfo=timezone.utc)
    assert next_week_start(wed).isoformat() == "2026-05-24T00:00:00+00:00"


# ---- async DB-backed tests ----


async def _seed_free_plan(db_session) -> Plan:
    plan = (await db_session.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if plan is not None:
        return plan
    plan = Plan(
        code="free",
        name="Free",
        description="test seed",
        word_cap_per_week=3000,
        memory_retention_days=30,
        features={},
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def _seed_pro_plan(db_session) -> Plan:
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one_or_none()
    if plan is not None:
        return plan
    plan = Plan(
        code="pro",
        name="Pro",
        description="test seed",
        word_cap_per_week=None,
        memory_retention_days=None,
        features={"agents": True, "mcp": True, "advanced_search": True},
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def _make_user(db_session, email: str) -> User:
    user = User(email=email)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture(autouse=True)
def enforce_billing_for_tests(monkeypatch):
    """Most quota tests want the enforcement path. Per-test overrides flip it
    back off via the same monkeypatch handle."""
    monkeypatch.setattr(
        "app.billing.quota.get_settings",
        lambda: type("S", (), {"billing_enforcement_enabled": True})(),
    )


@pytest.mark.asyncio
async def test_free_user_with_no_usage_is_allowed(db_session):
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "free@example.test")

    result = await WordQuota.check(db_session, user, estimated_words=100)
    assert result.allowed is True
    assert result.words_used == 0
    assert result.words_cap == 3000


@pytest.mark.asyncio
async def test_payment_mode_off_keeps_compatibility_uncapped(db_session, monkeypatch):
    """When billing_enforcement_enabled is false (the v1.0 default), free
    users stay in the uncapped compatibility path and are not blocked."""
    monkeypatch.setattr(
        "app.billing.quota.get_settings",
        lambda: type("S", (), {"billing_enforcement_enabled": False})(),
    )
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "paymentoff@example.test")
    await WordQuota.record(db_session, user, words=9_999)

    # Even though usage exceeds the configured cap, no cap is enforced.
    check = await WordQuota.check(db_session, user, estimated_words=10_000)
    assert check.allowed is True
    assert check.words_cap is None
    assert check.words_used == 9_999


@pytest.mark.asyncio
async def test_free_user_record_increments_then_check_reflects(db_session):
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "free2@example.test")

    rec1 = await WordQuota.record(db_session, user, words=500)
    assert rec1.words_used == 500
    assert rec1.words_cap == 3000
    assert rec1.allowed is True

    rec2 = await WordQuota.record(db_session, user, words=600)
    assert rec2.words_used == 1100
    assert rec2.allowed is True

    check = await WordQuota.check(db_session, user, estimated_words=0)
    assert check.words_used == 1100


@pytest.mark.asyncio
async def test_free_user_blocked_when_estimate_would_exceed(db_session):
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "blocked@example.test")
    await WordQuota.record(db_session, user, words=2_800)

    # 2800 + 250 = 3050 > 3000 cap -> blocked.
    check = await WordQuota.check(db_session, user, estimated_words=250)
    assert check.allowed is False
    assert check.words_used == 2_800
    assert check.words_cap == 3_000
    assert check.cap_exceeded is True


@pytest.mark.asyncio
async def test_pro_user_has_no_weekly_word_cap(db_session):
    await _seed_free_plan(db_session)
    pro = await _seed_pro_plan(db_session)
    user = await _make_user(db_session, "pro@example.test")

    # Simulate an active subscription pointing at the pro plan.
    from app.models.billing import Subscription

    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    result = await WordQuota.check(db_session, user, estimated_words=490_000)
    assert result.allowed is True
    assert result.words_cap is None

    rec = await WordQuota.record(db_session, user, words=490_000)
    assert rec.allowed is True
    assert rec.words_cap is None
    assert rec.words_used == 490_000

    check = await WordQuota.check(db_session, user, estimated_words=1_000_000)
    assert check.allowed is True
    assert check.words_cap is None


@pytest.mark.asyncio
async def test_past_due_subscription_uses_free_weekly_cap(db_session):
    await _seed_free_plan(db_session)
    pro = await _seed_pro_plan(db_session)
    user = await _make_user(db_session, "pastdue@example.test")
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="past_due",
        provider="tinkoff",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    result = await WordQuota.check(db_session, user, estimated_words=3_001)

    assert result.allowed is False
    assert result.words_cap == 3_000


@pytest.mark.asyncio
async def test_usage_week_row_uses_sunday_anchor(db_session):
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "week@example.test")

    now = datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc)  # Wednesday
    await WordQuota.record(db_session, user, words=42, now=now)

    rows = (
        await db_session.execute(select(UsageWeek).where(UsageWeek.user_id == user.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].week_start_utc.isoformat() == "2026-05-17"
    assert rows[0].words_used == 42


@pytest.mark.asyncio
async def test_new_week_creates_fresh_row(db_session):
    await _seed_free_plan(db_session)
    user = await _make_user(db_session, "twoweeks@example.test")

    wk1 = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)  # week of 05-17
    wk2 = datetime(2026, 5, 27, 0, 0, tzinfo=timezone.utc)  # week of 05-24
    await WordQuota.record(db_session, user, words=9_000, now=wk1)
    await WordQuota.record(db_session, user, words=200, now=wk2)

    rows = (
        await db_session.execute(
            select(UsageWeek).where(UsageWeek.user_id == user.id).order_by(UsageWeek.week_start_utc)
        )
    ).scalars().all()
    assert [r.words_used for r in rows] == [9_000, 200]

    # Quota check at wk2 sees only wk2 usage.
    check = await WordQuota.check(db_session, user, estimated_words=100, now=wk2)
    assert check.words_used == 200
    assert check.allowed is True
