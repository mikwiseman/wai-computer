"""Photo caption Q&A: a caption addressed to Wai answers about the image and
files the exchange; a label caption keeps the historical OCR+summary flow.
All bot I/O is captured in-memory — zero real network."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core.ocr import OcrError
from app.core.telegram_client import TelegramFile
from app.core.telegram_intent import CaptionRouteDecision
from app.models.item import Item
from app.models.telegram import TelegramAccount
from tests.test_telegram_agent_commands import (  # reuse the shared harness
    _Capture,
    _fake_item_pipeline,
    _linked_account,
    _stub_ocr,
)

pytestmark = pytest.mark.asyncio

_PHOTO = {
    "kind": "photo",
    "file_id": "file-qa",
    "file_unique_id": "uniq-qa",
    "mime_type": "image/jpeg",
    "file_size": 2048,
}


def _route_caption(monkeypatch, route: str, reason: str = "test") -> None:
    async def fake_classify(caption: str) -> CaptionRouteDecision:
        return CaptionRouteDecision(route, reason)  # type: ignore[arg-type]

    monkeypatch.setattr(telegram_routes, "classify_photo_caption", fake_classify)


def _stub_answer(monkeypatch, answer: str = "Это чек на 1200 ₽.") -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_answer(images, *, question, model=None):
        calls.append({"images": images, "question": question})
        return answer

    monkeypatch.setattr(telegram_routes, "answer_about_images", fake_answer)
    return calls


def _stub_enqueue(monkeypatch) -> list[Any]:
    enqueued: list[Any] = []

    async def fake_enqueue(db, item):
        enqueued.append(item)

    monkeypatch.setattr(telegram_routes, "enqueue_item_processing", fake_enqueue)
    return enqueued


async def _photo_message(
    db: AsyncSession,
    capture: _Capture,
    account: TelegramAccount,
    *,
    caption: str,
) -> None:
    await telegram_routes._handle_photo_message(
        db,
        capture,
        message={"message_id": 41, "chat": {"id": 9301}, "caption": caption},
        account=account,
        photo=dict(_PHOTO),
    )


async def test_question_caption_answers_and_files(db_session: AsyncSession, monkeypatch):
    user, account = await _linked_account(db_session, "tg-photo-qa@example.com", 9301)
    capture = _Capture()
    capture.file = TelegramFile("file-qa", "photos/receipt.jpg", 2048)
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    _route_caption(monkeypatch, "question", "assistant_high")
    answer_calls = _stub_answer(monkeypatch)
    enqueued = _stub_enqueue(monkeypatch)

    await _photo_message(db_session, capture, account, caption="сколько тут итого?")

    # The vision call got the actual photo bytes + the caption as the question.
    assert answer_calls == [
        {"images": [(b"jpeg-bytes", "image/jpeg")], "question": "сколько тут итого?"}
    ]
    # Status message is posted, then removed.
    assert "Смотрю на фото" in capture.messages[0]["text"]
    assert {"chat_id": 9301, "message_id": 1} in capture.deleted_messages
    # The reply is the answer, not a capture summary.
    reply = capture.messages[-1]
    assert "Это чек на 1200" in reply["text"]
    assert reply["parse_mode"] == "HTML"

    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert item.kind == "image"
    assert "Вопрос: сколько тут итого?" in item.body
    assert "Ответ: Это чек на 1200 ₽." in item.body
    assert item.metadata_["vision_qa"] is True
    assert item.metadata_["telegram"]["file_unique_id"] == "uniq-qa"
    assert enqueued == [item]
    assert account.active_context["ref_type"] == "item"
    assert account.active_context["ref_id"] == str(item.id)


async def test_label_caption_keeps_archive_flow(db_session: AsyncSession, monkeypatch):
    user, account = await _linked_account(db_session, "tg-photo-label@example.com", 9301)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    _stub_ocr(monkeypatch)
    _route_caption(monkeypatch, "label", "archive_high")

    async def unexpected_answer(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("label captions must not trigger vision Q&A")

    monkeypatch.setattr(telegram_routes, "answer_about_images", unexpected_answer)

    await _photo_message(db_session, capture, account, caption="чек за обед")

    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert "Распознанный текст с доски" in item.body
    assert "vision_qa" not in (item.metadata_ or {})
    # Reply is the capture summary from the item pipeline.
    assert "Краткое содержание" in capture.messages[-1]["text"]


async def test_question_caption_vision_failure_is_honest(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-photo-qafail@example.com", 9301)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _route_caption(monkeypatch, "question", "assistant_high")

    async def failing_answer(*args, **kwargs):
        raise OcrError("Image answer request failed: boom")

    monkeypatch.setattr(telegram_routes, "answer_about_images", failing_answer)

    await _photo_message(db_session, capture, account, caption="что это?")

    assert "Не смог ответить по этому фото" in capture.messages[-1]["text"]
    # Nothing was filed — the failure is explicit, not a silent degraded capture.
    items = (
        (await db_session.execute(select(Item).where(Item.user_id == user.id)))
        .scalars()
        .all()
    )
    assert items == []


async def test_uncaptioned_photo_never_calls_classifier(
    db_session: AsyncSession, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-photo-nocap@example.com", 9301)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    _stub_ocr(monkeypatch)

    async def unexpected_classify(caption):  # pragma: no cover - guard
        raise AssertionError("no-caption photos must skip the caption classifier")

    monkeypatch.setattr(telegram_routes, "classify_photo_caption", unexpected_classify)

    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 42, "chat": {"id": 9301}},
        account=account,
        photo=dict(_PHOTO),
    )

    assert "Принял фото" in capture.messages[0]["text"]
