"""Tests for Telegram-only account provisioning (emailless signup)."""


from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.api.routes.telegram import _guess_region, provision_user_from_telegram
from app.models.telegram import TelegramAccount, TelegramUpdate


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


# ---------------------------------------------------------------------------
# Onboarding copy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consent_prompt_copy_is_action_first():
    client = _FakeClient()
    await telegram_routes._send_consent_prompt(
        client, message={"message_id": 1, "chat": {"id": 5}}
    )
    text = client.messages[0][1]
    assert "второй мозг в Telegram" in text
    assert "саммари" in text
    assert telegram_routes.TERMS_URL in text
    assert telegram_routes.PRIVACY_URL in text


@pytest.mark.asyncio
async def test_consent_prompt_lead_overrides_first_line():
    client = _FakeClient()
    await telegram_routes._send_consent_prompt(
        client,
        message={"message_id": 1, "chat": {"id": 5}},
        lead=telegram_routes.TELEGRAM_PRESIGNUP_LEAD,
    )
    text = client.messages[0][1]
    assert text.startswith("Похоже, у тебя ещё нет аккаунта WaiComputer.")
    assert "не потеряется" in text
    # Consent copy still present under the custom lead.
    assert telegram_routes.TERMS_URL in text


def test_welcome_copy_is_short_and_action_first():
    welcome = telegram_routes.TELEGRAM_CONSENT_WELCOME
    assert welcome.startswith("Аккаунт создан ✅")
    assert "/help" in welcome
    # The old help wall is gone from the welcome.
    assert "Просто пиши или говори" not in welcome


def test_help_text_covers_headline_features():
    help_text = telegram_routes._telegram_help_text(linked=True)
    assert "Что умеет WaiComputer" in help_text
    assert "YouTube" in help_text
    assert "дайджест" in help_text
    assert "/web" in help_text and "/settings" in help_text
    # Status line logic preserved.
    assert "Telegram привязан" in help_text
    assert "Сначала привяжи Telegram" in telegram_routes._telegram_help_text(linked=False)


@pytest.mark.asyncio
async def test_web_and_settings_commands_reply_with_links(
    db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(telegram_routes.settings, "frontend_url", "https://wai.computer")
    _user_obj, account = await _provisioned_account(db_session, 560001)
    client = _FakeClient()
    handled_web = await telegram_routes._handle_account_command(
        db_session,
        client,
        message={"message_id": 1, "from": {"id": 560001}, "chat": {"id": 560001}},
        account=account,
        intent="web",
        arg="",
    )
    handled_settings = await telegram_routes._handle_account_command(
        db_session,
        client,
        message={"message_id": 2, "from": {"id": 560001}, "chat": {"id": 560001}},
        account=account,
        intent="settings",
        arg="",
    )
    assert handled_web and handled_settings
    texts = [t for _chat_id, t in client.messages]
    assert any("https://wai.computer/dashboard" in t for t in texts)
    assert any("#settings" in t for t in texts)


# ---------------------------------------------------------------------------
# Pre-signup message replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_update_stashes_presignup_message(
    db_session: AsyncSession, monkeypatch
):
    """A brand-new user's first message is buffered, not dropped."""
    db_session.add(
        TelegramUpdate(
            update_id=880001,
            status="accepted",
            received_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    client = _FakeClient()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_routes, "TelegramBotClient", lambda: client)
    monkeypatch.setattr(telegram_routes, "get_db_context", fake_db_context)

    await telegram_routes._handle_update(
        {
            "update_id": 880001,
            "message": {
                "message_id": 5,
                "from": {"id": 880001},
                "chat": {"id": 880001},
                "text": "запомни купить молоко",
            },
        }
    )

    row = await db_session.get(TelegramUpdate, 880001)
    assert row.status == "pending_signup"
    assert row.telegram_user_id == 880001
    assert row.payload["message"]["text"] == "запомни купить молоко"
    # The consent prompt was offered.
    assert any("Условия" in text for _chat_id, text in client.messages)


@pytest.mark.asyncio
async def test_collect_pending_signup_replays_caps_and_expires(
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc)
    # 6 fresh buffered messages — one over the cap of 5.
    for i in range(6):
        db_session.add(
            TelegramUpdate(
                update_id=882000 + i,
                status="pending_signup",
                telegram_user_id=559001,
                received_at=now,
                payload={"message": {"chat": {"id": 559001}, "text": f"m{i}"}},
            )
        )
    # A recent-by-update-id row that is nonetheless older than the 24h window.
    db_session.add(
        TelegramUpdate(
            update_id=882100,
            status="pending_signup",
            telegram_user_id=559001,
            received_at=now - timedelta(hours=25),
            payload={"message": {"chat": {"id": 559001}, "text": "old"}},
        )
    )
    await db_session.commit()

    eligible = await telegram_routes._collect_pending_signup_replays(
        db_session, telegram_user_id=559001
    )

    assert len(eligible) <= telegram_routes.TELEGRAM_PENDING_SIGNUP_REPLAY_LIMIT
    ids = {row.update_id for row in eligible}
    # The stale message is skipped even though its update_id is the newest.
    assert 882100 not in ids
    assert (await db_session.get(TelegramUpdate, 882100)).status == "skipped"
    # The oldest message beyond the cap is skipped too.
    assert (await db_session.get(TelegramUpdate, 882000)).status == "skipped"


@pytest.mark.asyncio
async def test_consent_callback_replays_pending_signup_message(
    db_session: AsyncSession, monkeypatch
):
    """After consent, the buffered first message is re-routed and marked done."""
    db_session.add(
        TelegramUpdate(
            update_id=881001,
            status="pending_signup",
            telegram_user_id=558001,
            received_at=datetime.now(timezone.utc),
            payload={
                "update_id": 881001,
                "message": {
                    "message_id": 9,
                    "from": {"id": 558001},
                    "chat": {"id": 558001},
                    "voice": {"file_id": "file-id"},
                },
            },
        )
    )
    await db_session.commit()

    routed: list[dict] = []

    async def fake_route(db, client, *, message, account):
        routed.append(message)

    monkeypatch.setattr(telegram_routes, "_route_account_message", fake_route)

    client = _FakeClient()
    await telegram_routes._handle_consent_callback(
        db_session,
        client,
        callback_id="cb-replay",
        from_user={"id": 558001, "first_name": "New", "language_code": "ru"},
        chat_id=558001,
        message_id=42,
    )

    account = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 558001)
        )
    ).scalar_one()
    assert account.telegram_chat_id == 558001
    # The buffered voice note was re-routed exactly once.
    assert len(routed) == 1
    assert routed[0]["voice"]["file_id"] == "file-id"
    # And its idempotency row is closed out.
    assert (await db_session.get(TelegramUpdate, 881001)).status == "completed"
    # The welcome promised the message is already being handled.
    assert any("Уже обрабатываю" in edit[2] for edit in client.edits)


@pytest.mark.asyncio
async def test_replay_pending_signup_update_marks_failed_on_error(
    db_session: AsyncSession, monkeypatch
):
    _user_obj, account = await _provisioned_account(db_session, 561001)
    row = TelegramUpdate(
        update_id=883001,
        status="pending_signup",
        telegram_user_id=561001,
        received_at=datetime.now(timezone.utc),
        payload={"message": {"chat": {"id": 561001}, "text": "boom"}},
    )
    db_session.add(row)
    await db_session.commit()

    async def boom_route(db, client, *, message, account):
        raise ValueError("kaboom")

    monkeypatch.setattr(telegram_routes, "_route_account_message", boom_route)

    client = _FakeClient()
    await telegram_routes._replay_pending_signup_update(
        db_session, client, account=account, row=row
    )

    refreshed = await db_session.get(TelegramUpdate, 883001)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "ValueError"


@pytest.mark.asyncio
async def test_consent_callback_without_pending_sends_plain_welcome(
    db_session: AsyncSession,
):
    client = _FakeClient()
    await telegram_routes._handle_consent_callback(
        db_session,
        client,
        callback_id="cb-plain",
        from_user={"id": 557101, "first_name": "Z", "language_code": "ru"},
        chat_id=557101,
        message_id=7,
    )
    # No buffered messages -> welcome has no "already processing" suffix.
    welcome = client.edits[0][2]
    assert "Аккаунт создан" in welcome
    assert "Уже обрабатываю" not in welcome


