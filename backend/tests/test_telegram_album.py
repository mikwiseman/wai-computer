"""Telegram photo albums (media groups): DB-backed buffering with a debounced
Celery task, one combined vision pass, one material, one reply. All bot I/O is
captured in-memory — zero real network."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core.telegram_intent import CaptionRouteDecision
from app.models.item import Item
from app.models.telegram import TelegramAccount, TelegramMediaGroupPart
from app.tasks import telegram_album_import
from tests.test_telegram_agent_commands import (  # reuse the shared harness
    _Capture,
    _fake_item_pipeline,
    _linked_account,
)


def _album_message(message_id: int, *, group: str = "album-1", caption: str | None = None):
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat": {"id": 9401},
        "media_group_id": group,
        "photo": [
            {
                "file_id": f"file-{message_id}",
                "file_unique_id": f"uniq-{message_id}",
                "width": 1280,
                "height": 720,
                "file_size": 2048,
            }
        ],
    }
    if caption is not None:
        message["caption"] = caption
    return message


def _capture_scheduler(monkeypatch) -> list[dict[str, Any]]:
    scheduled: list[dict[str, Any]] = []

    def fake_apply_async(*, kwargs, countdown):
        scheduled.append({"kwargs": kwargs, "countdown": countdown})

    monkeypatch.setattr(
        "app.tasks.telegram_album_import.process_telegram_media_group_task.apply_async",
        fake_apply_async,
    )
    return scheduled


async def _buffer(
    db: AsyncSession, capture: _Capture, account: TelegramAccount, message: dict[str, Any]
) -> None:
    await telegram_routes._buffer_album_photo(
        db, capture, message=message, account=account
    )


# ---------------------------------------------------------------------------
# _buffer_album_photo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_part_buffers_and_schedules_once(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-album-1@example.com", 9401)
    capture = _Capture()
    scheduled = _capture_scheduler(monkeypatch)

    await _buffer(db_session, capture, account, _album_message(11))
    await _buffer(db_session, capture, account, _album_message(12))

    parts = (
        (await db_session.execute(select(TelegramMediaGroupPart))).scalars().all()
    )
    assert sorted(p.message_id for p in parts) == [11, 12]
    assert all(p.telegram_user_id == account.telegram_user_id for p in parts)
    # Only the FIRST buffered part schedules the debounced task.
    assert len(scheduled) == 1
    assert scheduled[0]["kwargs"] == {
        "media_group_id": "album-1",
        "telegram_user_id": account.telegram_user_id,
    }
    assert scheduled[0]["countdown"] == telegram_routes.ALBUM_DEBOUNCE_SECONDS


@pytest.mark.asyncio
async def test_duplicate_part_is_ignored(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-album-2@example.com", 9401)
    capture = _Capture()
    scheduled = _capture_scheduler(monkeypatch)

    await _buffer(db_session, capture, account, _album_message(21, group="album-2"))
    await _buffer(db_session, capture, account, _album_message(21, group="album-2"))

    parts = (
        (
            await db_session.execute(
                select(TelegramMediaGroupPart).where(
                    TelegramMediaGroupPart.media_group_id == "album-2"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(parts) == 1
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_straggler_after_processed_group_falls_back_to_single_photo(
    db_session, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-album-3@example.com", 9401)
    capture = _Capture()
    scheduled = _capture_scheduler(monkeypatch)
    db_session.add(
        TelegramMediaGroupPart(
            media_group_id="album-3",
            telegram_user_id=account.telegram_user_id,
            chat_id=9401,
            message_id=30,
            message=_album_message(30, group="album-3"),
            processed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    single_calls: list[dict[str, Any]] = []

    async def fake_single(db, client, *, message, account, photo):
        single_calls.append({"message_id": message["message_id"], "photo": photo})

    monkeypatch.setattr(telegram_routes, "_handle_photo_message", fake_single)

    await _buffer(db_session, capture, account, _album_message(31, group="album-3"))

    assert [c["message_id"] for c in single_calls] == [31]
    assert scheduled == []


# ---------------------------------------------------------------------------
# _process_photo_album
# ---------------------------------------------------------------------------


def _parts_for(
    account: TelegramAccount, messages: list[dict[str, Any]]
) -> list[TelegramMediaGroupPart]:
    return [
        TelegramMediaGroupPart(
            media_group_id=str(m["media_group_id"]),
            telegram_user_id=account.telegram_user_id,
            chat_id=m["chat"]["id"],
            message_id=m["message_id"],
            message=m,
        )
        for m in messages
    ]


def _stub_album_ocr(monkeypatch, text: str) -> list[list[tuple[bytes, str]]]:
    calls: list[list[tuple[bytes, str]]] = []

    async def fake_ocr(images, *, model=None):
        calls.append(images)
        return text

    monkeypatch.setattr(telegram_routes, "ocr_images", fake_ocr)
    return calls


@pytest.mark.asyncio
async def test_album_label_flow_files_one_item(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-album-4@example.com", 9401)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    ocr_calls = _stub_album_ocr(
        monkeypatch, "Image 1: слайд\nText: Roadmap\n\nImage 2: слайд\nText: Q3"
    )
    messages = [
        _album_message(41, group="album-4", caption="слайды с митапа"),
        _album_message(42, group="album-4"),
    ]
    parts = _parts_for(account, messages)
    db_session.add_all(parts)
    await db_session.flush()

    async def fake_classify(caption: str) -> CaptionRouteDecision:
        return CaptionRouteDecision("label", "archive_high")

    monkeypatch.setattr(telegram_routes, "classify_photo_caption", fake_classify)

    await telegram_routes._process_photo_album(
        db_session, capture, account=account, parts=parts
    )

    # One combined vision pass over both photos, in message order.
    assert len(ocr_calls) == 1
    assert ocr_calls[0] == [(b"jpeg-bytes", "image/jpeg"), (b"jpeg-bytes", "image/jpeg")]

    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert item.kind == "image"
    assert "слайды с митапа" in item.body
    assert "Roadmap" in item.body
    assert item.metadata_["telegram"]["media_group_id"] == "album-4"
    assert item.metadata_["telegram"]["count"] == 2
    assert item.metadata_["telegram"]["file_unique_ids"] == ["uniq-41", "uniq-42"]

    assert all(p.processed_at is not None for p in parts)
    assert "Принял альбом (2 фото)" in capture.messages[0]["text"]
    assert {"chat_id": 9401, "message_id": 1} in capture.deleted_messages
    assert "Краткое содержание" in capture.messages[-1]["text"]
    assert account.active_context["ref_id"] == str(item.id)


@pytest.mark.asyncio
async def test_album_question_flow_answers_and_files(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-album-5@example.com", 9401)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)

    answer_calls: list[dict[str, Any]] = []

    async def fake_answer(images, *, question, model=None):
        answer_calls.append({"count": len(images), "question": question})
        return "На двух слайдах — план Q3."

    monkeypatch.setattr(telegram_routes, "answer_about_images", fake_answer)

    async def fake_classify(caption: str) -> CaptionRouteDecision:
        return CaptionRouteDecision("question", "assistant_high")

    monkeypatch.setattr(telegram_routes, "classify_photo_caption", fake_classify)

    enqueued: list[Any] = []

    async def fake_enqueue(db, item):
        enqueued.append(item)

    monkeypatch.setattr(telegram_routes, "enqueue_item_processing", fake_enqueue)

    messages = [
        _album_message(51, group="album-5"),
        _album_message(52, group="album-5", caption="что на этих слайдах?"),
    ]
    parts = _parts_for(account, messages)
    db_session.add_all(parts)
    await db_session.flush()

    await telegram_routes._process_photo_album(
        db_session, capture, account=account, parts=parts
    )

    assert answer_calls == [{"count": 2, "question": "что на этих слайдах?"}]
    assert any("На двух слайдах" in m["text"] for m in capture.messages)

    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert "Вопрос: что на этих слайдах?" in item.body
    assert item.metadata_["vision_qa"] is True
    assert enqueued == [item]
    assert all(p.processed_at is not None for p in parts)


@pytest.mark.asyncio
async def test_album_reruns_dedupe_on_media_group(db_session, monkeypatch):
    """A duplicate task run (double schedule race) must not file a second item."""
    user, account = await _linked_account(db_session, "tg-album-6@example.com", 9401)
    capture = _Capture()
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    _stub_album_ocr(monkeypatch, "Image 1: чек\nText: 1200")

    messages = [_album_message(61, group="album-6", caption="чек")]

    async def fake_classify(caption: str) -> CaptionRouteDecision:
        return CaptionRouteDecision("label", "archive_high")

    monkeypatch.setattr(telegram_routes, "classify_photo_caption", fake_classify)

    for _ in range(2):
        parts = _parts_for(account, messages)
        db_session.add_all(parts)
        await db_session.flush()
        await telegram_routes._process_photo_album(
            db_session, capture, account=account, parts=parts
        )
        for part in parts:
            await db_session.delete(part)
        await db_session.flush()

    items = (
        (await db_session.execute(select(Item).where(Item.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(items) == 1


# ---------------------------------------------------------------------------
# Celery task wrapper + _run
# ---------------------------------------------------------------------------


def _coro_factory(*, raises: Exception | None = None):
    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises

    return _inner


def test_task_timeout_captures_anomaly() -> None:
    with (
        patch.object(
            telegram_album_import, "_run", _coro_factory(raises=SoftTimeLimitExceeded())
        ),
        patch.object(telegram_album_import, "capture_sentry_anomaly") as anomaly,
    ):
        with pytest.raises(SoftTimeLimitExceeded):
            telegram_album_import.process_telegram_media_group_task(
                media_group_id="g", telegram_user_id=1
            )
    anomaly.assert_called_once()


def test_task_failure_captures_exception_and_raises() -> None:
    with (
        patch.object(
            telegram_album_import, "_run", _coro_factory(raises=ValueError("boom"))
        ),
        patch.object(telegram_album_import, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(ValueError):
            telegram_album_import.process_telegram_media_group_task(
                media_group_id="g", telegram_user_id=1
            )
    cap.assert_called_once()


@pytest.mark.asyncio
async def test_run_drops_when_account_gone(db_session, monkeypatch) -> None:
    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(telegram_album_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(
        telegram_album_import, "TelegramBotClient", lambda: SimpleNamespace()
    )

    called: list[Any] = []

    async def fake_process(db, client, *, account, parts):  # pragma: no cover - guard
        called.append(parts)

    monkeypatch.setattr(
        "app.api.routes.telegram._process_photo_album", fake_process
    )

    await telegram_album_import._run(media_group_id="missing", telegram_user_id=404)
    assert called == []


@pytest.mark.asyncio
async def test_run_processes_unprocessed_parts_in_message_order(
    db_session, monkeypatch
) -> None:
    _user, account = await _linked_account(db_session, "tg-album-7@example.com", 9401)

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(telegram_album_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(
        telegram_album_import, "TelegramBotClient", lambda: SimpleNamespace()
    )

    messages = [_album_message(72, group="album-7"), _album_message(71, group="album-7")]
    db_session.add_all(_parts_for(account, messages))
    db_session.add(
        TelegramMediaGroupPart(
            media_group_id="album-7",
            telegram_user_id=account.telegram_user_id,
            chat_id=9401,
            message_id=70,
            message=_album_message(70, group="album-7"),
            processed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    seen: list[list[int]] = []

    async def fake_process(db, client, *, account, parts):
        seen.append([p.message_id for p in parts])

    monkeypatch.setattr(
        "app.api.routes.telegram._process_photo_album", fake_process
    )

    await telegram_album_import._run(
        media_group_id="album-7", telegram_user_id=account.telegram_user_id
    )
    # Only unprocessed parts, ordered by message_id.
    assert seen == [[71, 72]]
