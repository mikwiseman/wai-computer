"""Approved-action side-effect runners (P3): server-side recipient grounding,
no-fallback refusals."""

from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import companion_actuators as act
from app.core.companion_actuators import ActuationError
from app.models.telegram import TelegramAccount
from app.models.user import User


class FakeTelegram:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return {"message_id": 42}


@pytest_asyncio.fixture
async def user_with_telegram(db_session):
    user = User(email=f"tg-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    acct = TelegramAccount(
        user_id=user.id,
        telegram_user_id=int(uuid4().int % 1_000_000_000),
        telegram_chat_id=555123,
    )
    db_session.add(acct)
    await db_session.flush()
    return user.id


async def test_send_grounds_to_own_chat_and_ignores_supplied_chat_id(
    db_session, user_with_telegram
):
    fake = FakeTelegram()
    receipt = await act.execute_action(
        db_session,
        user_id=user_with_telegram,
        tool_name="send_message_telegram",
        # A hostile/hallucinated chat_id in args must be ignored.
        args={"text": "running late", "chat_id": 999999},
        telegram_client=fake,
    )
    assert fake.sent == [(555123, "running late")]  # own chat, NOT 999999
    assert receipt["chat_id"] == 555123
    assert receipt["message_id"] == 42


async def test_empty_text_is_refused(db_session, user_with_telegram):
    with pytest.raises(ActuationError) as exc:
        await act.execute_action(
            db_session,
            user_id=user_with_telegram,
            tool_name="send_message_telegram",
            args={"text": "   "},
            telegram_client=FakeTelegram(),
        )
    assert exc.value.code == "empty_text"


async def test_no_linked_account_raises(db_session):
    user = User(email=f"noacct-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    with pytest.raises(ActuationError) as exc:
        await act.execute_action(
            db_session,
            user_id=user.id,
            tool_name="send_message_telegram",
            args={"text": "hi"},
            telegram_client=FakeTelegram(),
        )
    assert exc.value.code == "no_telegram_account"


async def test_unknown_tool_raises(db_session, user_with_telegram):
    with pytest.raises(ActuationError) as exc:
        await act.execute_action(
            db_session,
            user_id=user_with_telegram,
            tool_name="launch_missiles",
            args={},
            telegram_client=FakeTelegram(),
        )
    assert exc.value.code == "no_executor"
