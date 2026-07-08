"""Integration test: forwarding a link to the Telegram bot ingests + replies.

Drives ``_handle_url_message`` directly with a fake bot client and stubbed
fetch + LLM, exercising the real ingest -> process -> reply path.
"""

from uuid import uuid4

import pytest

from app.api.routes import telegram as telegram_routes
from app.core import item_processing as processing_module
from app.core import item_summary as item_summary_module
from app.core.source_fetch import FetchedContent, SourceFetchError
from app.core.summarizer import KeyMoment, SummaryResult
from app.models.item import Item
from app.models.telegram import TelegramAccount
from app.models.user import User

pytestmark = pytest.mark.asyncio


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(
        self, chat_id, text, *, reply_to_message_id=None, parse_mode=None, reply_markup=None
    ):
        self.messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )
        return {"message_id": len(self.messages)}

    async def send_chat_action(self, chat_id, action):
        return None


async def _linked_account(db) -> TelegramAccount:
    user = User(email=f"tg-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    account = TelegramAccount(
        user_id=user.id, telegram_user_id=int(uuid4().int % 1_000_000_000)
    )
    db.add(account)
    await db.flush()
    return account


def _stub_llm(monkeypatch) -> None:
    async def fake_summarize(text, **kwargs):
        return SummaryResult(
            title="Solar Explainer",
            summary="A clear explainer about solar economics in 2026.",
            key_points=["costs fell"],
            decisions=[],
            action_items=[{"task": "read the paper", "owner": None, "due": None,
                           "priority": "high"}],
            topics=["energy"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="positive",
            highlights=[],
        )

    async def fake_moments(text, **kwargs):
        return [
            KeyMoment(timestamp="00:42", moment="Thesis stated",
                      why_it_matters="frames it", quote=None, importance="high"),
        ]

    async def fake_embed(texts, **_):
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(item_summary_module, "summarize_content", fake_summarize)
    monkeypatch.setattr(item_summary_module, "extract_key_moments", fake_moments)
    monkeypatch.setattr(processing_module, "generate_embeddings", fake_embed)


async def test_forward_youtube_link_replies_with_summary(db_session, monkeypatch) -> None:
    account = await _linked_account(db_session)
    _stub_llm(monkeypatch)

    async def fake_fetch(url, **kwargs):
        return FetchedContent(
            source_type="youtube", kind="video", url=url,
            title=None, body="A long transcript about solar power.",
            metadata={"video_id": "abc"},
        )

    monkeypatch.setattr(processing_module, "fetch_url", fake_fetch)
    client = FakeTelegramClient()
    message = {"chat": {"id": 999, "type": "private"}, "message_id": 5}

    await telegram_routes._handle_url_message(
        db_session, client, message=message, account=account,
        url="https://youtu.be/abc",
    )

    assert len(client.messages) >= 1
    reply = client.messages[-1]["text"]
    assert client.messages[-1]["parse_mode"] == "HTML"
    assert "Solar Explainer" in reply
    assert "Key moments" in reply
    assert "[00:42] Thesis stated" in reply

    # Item persisted with summary.
    item = (
        await db_session.execute(
            Item.__table__.select().where(Item.user_id == account.user_id)
        )
    ).first()
    assert item is not None


async def test_forward_instagram_link_replies_share_required(db_session, monkeypatch) -> None:
    account = await _linked_account(db_session)

    async def fake_fetch(url, **kwargs):
        raise SourceFetchError(
            "Instagram doesn't allow apps to read its posts. Share the file.",
            code="instagram_share_required",
        )

    monkeypatch.setattr(processing_module, "fetch_url", fake_fetch)
    client = FakeTelegramClient()
    message = {"chat": {"id": 7, "type": "private"}, "message_id": 9}

    await telegram_routes._handle_url_message(
        db_session, client, message=message, account=account,
        url="https://www.instagram.com/reel/xyz/",
    )

    reply = client.messages[-1]["text"]
    assert "Instagram" in reply
    assert "Share the file" in reply


async def test_forward_same_link_twice_is_idempotent(db_session, monkeypatch) -> None:
    account = await _linked_account(db_session)
    _stub_llm(monkeypatch)
    calls = {"n": 0}

    async def fake_fetch(url, **kwargs):
        calls["n"] += 1
        return FetchedContent(
            source_type="article", kind="article", url=url,
            title="A", body="body text", metadata={},
        )

    monkeypatch.setattr(processing_module, "fetch_url", fake_fetch)
    client = FakeTelegramClient()
    message = {"chat": {"id": 1, "type": "private"}, "message_id": 1}
    url = "https://example.com/post"

    await telegram_routes._handle_url_message(
        db_session, client, message=message, account=account, url=url
    )
    # Second forward: item already exists + already promoted -> no re-fetch.
    items = (
        await db_session.execute(
            Item.__table__.select().where(Item.user_id == account.user_id)
        )
    ).fetchall()
    assert len(items) == 1
