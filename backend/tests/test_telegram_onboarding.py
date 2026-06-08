"""Tests for Telegram-only account provisioning (emailless signup)."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.telegram import _guess_region, provision_user_from_telegram
from app.models.telegram import TelegramAccount
from app.models.user import User


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


class _FakeClient:
    def __init__(self) -> None:
        self.answered: list[tuple[str, str | None]] = []
        self.edits: list[tuple[int, int, str]] = []
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[str, bytes]] = []

    async def answer_callback_query(self, callback_id, text=None):
        self.answered.append((callback_id, text))

    async def edit_message_text(self, chat_id, message_id, text, **_kwargs):
        self.edits.append((chat_id, message_id, text))

    async def send_message(self, chat_id, text, **_kwargs):
        self.messages.append((chat_id, text))

    async def send_document(self, chat_id, *, filename, data, **_kwargs):
        self.documents.append((filename, data))


@pytest.mark.asyncio
async def test_consent_callback_provisions_account(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_consent_callback

    client = _FakeClient()
    await _handle_consent_callback(
        db_session,
        client,
        callback_id="cb1",
        from_user={"id": 557001, "first_name": "Z", "language_code": "ru"},
        chat_id=557001,
        message_id=42,
    )
    account = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 557001)
        )
    ).scalar_one()
    assert account.telegram_chat_id == 557001
    assert client.answered == [("cb1", "Готово!")]
    # The consent message is edited into a welcome (buttons removed).
    assert client.edits and "создан" in client.edits[0][2]


@pytest.mark.asyncio
async def test_consent_callback_rejects_bot(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_consent_callback

    client = _FakeClient()
    await _handle_consent_callback(
        db_session,
        client,
        callback_id="cb2",
        from_user={"id": 999, "is_bot": True},
        chat_id=999,
        message_id=1,
    )
    assert client.answered == [("cb2", "Не удалось создать аккаунт.")]
    assert not client.edits


def test_email_verification_token_roundtrip():
    from uuid import uuid4

    from app.core.security import (
        create_email_verification_token,
        decode_email_verification_token,
    )

    uid = uuid4()
    token = create_email_verification_token(uid, "a@b.com")
    assert decode_email_verification_token(token) == (uid, "a@b.com")
    assert decode_email_verification_token("garbage") is None


@pytest.mark.asyncio
async def test_email_command_sends_verification_without_setting_email(db_session, monkeypatch):
    from app.api.routes import telegram as tg

    user, account = await _provisioned_account(db_session, 560001)
    sent: list[tuple[str, str]] = []

    async def fake_send(to_email, token, *, locale="en"):
        sent.append((to_email, locale))

    monkeypatch.setattr("app.core.email.send_email_verification_email", fake_send)
    client = _FakeClient()
    msg = {"message_id": 1, "from": {"id": 560001}, "chat": {"id": 560001}}
    await tg._handle_email_command(
        db_session, client, message=msg, account=account, arg="Me@Example.com"
    )
    assert sent and sent[0][0] == "me@example.com"
    assert client.messages and "me@example.com" in client.messages[-1][1]
    # Verify-then-link: the email is NOT attached until the link is clicked.
    await db_session.refresh(user)
    assert user.email is None


@pytest.mark.asyncio
async def test_email_command_rejects_taken_email(db_session, monkeypatch):
    from app.api.routes import telegram as tg

    db_session.add(User(email="taken@example.com"))
    await db_session.flush()
    _user, account = await _provisioned_account(db_session, 560002)

    async def fake_send(*a, **k):  # should never be called
        raise AssertionError("must not send for a taken email")

    monkeypatch.setattr("app.core.email.send_email_verification_email", fake_send)
    client = _FakeClient()
    msg = {"message_id": 1, "from": {"id": 560002}, "chat": {"id": 560002}}
    await tg._handle_email_command(
        db_session, client, message=msg, account=account, arg="taken@example.com"
    )
    assert client.messages and "уже привязан" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_confirm_email_attaches_verified_address(db_session):
    from app.api.routes.auth import confirm_email
    from app.core.security import create_email_verification_token

    user, _account = await _provisioned_account(db_session, 560003)
    token = create_email_verification_token(user.id, "new@example.com")
    resp = await confirm_email(token, db_session)
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.email == "new@example.com"


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


async def _provisioned_account(db_session: AsyncSession, telegram_user_id: int):
    user = await provision_user_from_telegram(
        db_session,
        from_user={"id": telegram_user_id, "first_name": "T"},
        telegram_chat_id=telegram_user_id,
    )
    account = (
        await db_session.execute(
            select(TelegramAccount).where(
                TelegramAccount.telegram_user_id == telegram_user_id
            )
        )
    ).scalar_one()
    return user, account


@pytest.mark.asyncio
async def test_web_login_command_dms_verify_link(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_web_login_command

    user, account = await _provisioned_account(db_session, 558001)
    client = _FakeClient()
    msg = {"message_id": 1, "from": {"id": 558001}, "chat": {"id": 558001}}
    await _handle_web_login_command(db_session, client, message=msg, account=account)
    await db_session.refresh(user)
    assert user.magic_link_token is not None
    assert user.magic_link_expires is not None
    assert client.messages and "/auth/verify?token=" in client.messages[0][1]


@pytest.mark.asyncio
async def test_export_command_sends_data_dump(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_export_command

    _user, account = await _provisioned_account(db_session, 559001)
    client = _FakeClient()
    msg = {"message_id": 1, "from": {"id": 559001}, "chat": {"id": 559001}}
    await _handle_export_command(db_session, client, message=msg, account=account)
    assert client.documents
    filename, data = client.documents[0]
    assert filename == "waicomputer-export.json"
    payload = json.loads(data.decode("utf-8"))
    assert "recordings" in payload
    assert "action_items" in payload
    assert "memory" in payload


@pytest.mark.asyncio
async def test_delete_callback_removes_account_and_data(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_delete_callback

    user, account = await _provisioned_account(db_session, 559003)
    user_id = user.id
    client = _FakeClient()
    await _handle_delete_callback(
        db_session,
        client,
        account=account,
        callback_id="cb",
        chat_id=559003,
        message_id=5,
    )
    assert client.answered == [("cb", "Удалено.")]
    assert await db_session.get(User, user_id) is None
    # The telegram_accounts row is cascade-deleted with the user.
    gone = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 559003)
        )
    ).scalar_one_or_none()
    assert gone is None


@pytest.mark.asyncio
async def test_mcp_command_mints_readonly_token(db_session: AsyncSession):
    from app.api.routes.telegram import _handle_mcp_command
    from app.core.api_keys import API_KEY_READ_SCOPE
    from app.models.api_key import ApiKey

    user, account = await _provisioned_account(db_session, 558002)
    client = _FakeClient()
    msg = {"message_id": 1, "from": {"id": 558002}, "chat": {"id": 558002}}
    await _handle_mcp_command(db_session, client, message=msg, account=account)
    key = (
        await db_session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    ).scalar_one()
    assert key.scopes == [API_KEY_READ_SCOPE]
    assert key.prefix.startswith("wc_live_")
    assert client.messages
    assert "wc_live_" in client.messages[0][1]
    assert "wai.computer/mcp" in client.messages[0][1]
