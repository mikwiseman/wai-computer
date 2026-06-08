"""Tests for Telegram-only account provisioning (emailless signup)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.telegram import _guess_region, provision_user_from_telegram
from app.models.telegram import TelegramAccount


def test_guess_region():
    assert _guess_region("ru") == "ru"
    assert _guess_region("ru-RU") == "ru"
    assert _guess_region("en") == "global"
    assert _guess_region(None) == "global"
    assert _guess_region("") == "global"


@pytest.mark.asyncio
async def test_provision_creates_emailless_account(db_session: AsyncSession):
    from_user = {
        "id": 555001,
        "is_bot": False,
        "first_name": "Mik",
        "last_name": "W",
        "username": "mik",
        "language_code": "ru",
    }
    user = await provision_user_from_telegram(
        db_session, from_user=from_user, telegram_chat_id=999001
    )
    assert user is not None
    assert user.email is None
    assert user.password_hash is None
    assert user.region == "ru"
    assert user.first_name == "Mik"
    assert user.signup_origin == "telegram"
    assert user.account_status == "active"
    # Legal acceptance stamped with the telegram source.
    assert user.legal_acceptance_source == "telegram"
    assert user.legal_terms_accepted_at is not None
    assert user.legal_terms_version is not None

    account = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 555001)
        )
    ).scalar_one()
    assert account.user_id == user.id
    assert account.telegram_chat_id == 999001


@pytest.mark.asyncio
async def test_provision_is_idempotent(db_session: AsyncSession):
    from_user = {"id": 555002, "first_name": "A", "language_code": "en"}
    u1 = await provision_user_from_telegram(db_session, from_user=from_user, telegram_chat_id=1)
    u2 = await provision_user_from_telegram(db_session, from_user=from_user, telegram_chat_id=1)
    assert u1 is not None and u2 is not None
    assert u1.id == u2.id
    assert u1.region == "global"
    # Only one user row exists for this telegram id.
    accounts = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 555002)
        )
    ).scalars().all()
    assert len(accounts) == 1


@pytest.mark.asyncio
async def test_provision_rejects_bots_and_sentinels(db_session: AsyncSession):
    assert (
        await provision_user_from_telegram(
            db_session, from_user={"id": 424242, "is_bot": True}, telegram_chat_id=1
        )
        is None
    )
    # Anonymous group admin + Telegram service ids must never key an account.
    assert (
        await provision_user_from_telegram(
            db_session, from_user={"id": 1087968824}, telegram_chat_id=1
        )
        is None
    )
    assert (
        await provision_user_from_telegram(
            db_session, from_user={"id": 777000}, telegram_chat_id=1
        )
        is None
    )
    # A non-integer id is not a real user.
    assert (
        await provision_user_from_telegram(
            db_session, from_user={"id": "nope"}, telegram_chat_id=1
        )
        is None
    )


@pytest.mark.asyncio
async def test_multiple_emailless_users_coexist(db_session: AsyncSession):
    """The partial unique index must allow many NULL-email accounts."""
    u1 = await provision_user_from_telegram(
        db_session, from_user={"id": 556001, "first_name": "X"}, telegram_chat_id=1
    )
    u2 = await provision_user_from_telegram(
        db_session, from_user={"id": 556002, "first_name": "Y"}, telegram_chat_id=2
    )
    assert u1 is not None and u2 is not None
    assert u1.id != u2.id
    assert u1.email is None and u2.email is None
