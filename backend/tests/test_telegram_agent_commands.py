"""Coverage for Telegram photo/forwarded-text capture, agent-run replies,
approval formatting, callback dispatch, /email edges, and post-approval
agent resume. All bot I/O is captured in-memory — zero real network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core.agent_dispatch import AgentDispatchError
from app.core.ocr import OcrError
from app.core.summarizer import SummaryResult
from app.core.telegram_client import TelegramFile, TelegramFileTooLargeError
from app.models.agent import Agent, AgentRun
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemChunk
from app.models.telegram import TelegramAccount
from app.models.user import User


class _Capture:
    """Fake TelegramBotClient that records every outgoing call."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.deleted_messages: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []
        self.edited_messages: list[dict[str, Any]] = []
        self.file = TelegramFile("file-id", "photos/file.jpg", 12)
        self.data = b"telegram photo"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = len(self.messages) + 1
        self.messages.append(
            {
                "message_id": message_id,
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": message_id}

    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        self.callback_answers.append({"id": callback_query_id, "text": text})

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        self.edited_messages.append(
            {"chat_id": chat_id, "message_id": message_id, "text": text}
        )
        return {"message_id": message_id}

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.actions.append({"chat_id": chat_id, "action": action})

    async def get_file(self, file_id: str) -> TelegramFile:
        return self.file

    async def download_file(
        self, file: TelegramFile, *, max_bytes: int | None = None
    ) -> bytes:
        if max_bytes is not None and len(self.data) > max_bytes:
            raise TelegramFileTooLargeError("Telegram file exceeds configured limit")
        return self.data


class _UncappedDownloadCapture(_Capture):
    """Returns the payload regardless of max_bytes, forcing the post-download check."""

    async def download_file(
        self, file: TelegramFile, *, max_bytes: int | None = None
    ) -> bytes:
        return self.data


async def _linked_account(
    db: AsyncSession, email: str, telegram_id: int
) -> tuple[User, TelegramAccount]:
    user = User(email=email, password_hash="hash")
    db.add(user)
    await db.flush()
    account = TelegramAccount(
        user_id=user.id, telegram_user_id=telegram_id, telegram_chat_id=telegram_id
    )
    db.add(account)
    await db.commit()
    return user, account


async def _agent_with_run(
    db: AsyncSession,
    user: User,
    *,
    status: str = "pending",
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> tuple[Agent, AgentRun]:
    agent = Agent(user_id=user.id, name="Wai", kind="wai", trigger_type="chat")
    db.add(agent)
    await db.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"test:{uuid4().hex}",
        trigger_kind="manual",
        status=status,
        result=result,
        error=error,
    )
    db.add(run)
    await db.flush()
    return agent, run


def _pending_action(
    user: User,
    run: AgentRun,
    *,
    preview: str | None = "Послать привет",
    recipient: str | None = None,
    status: str = "pending",
) -> CompanionPendingAction:
    manifest: dict[str, Any] = {"preview": preview} if preview else {}
    return CompanionPendingAction(
        user_id=user.id,
        agent_run_id=run.id,
        kind="send",
        tool_name="send_message_telegram",
        action_manifest=manifest,
        payload_hmac="0" * 64,
        idempotency_key=f"key:{uuid4().hex}",
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        recipient_display=recipient,
    )


def _fake_item_pipeline(monkeypatch) -> None:
    """Make ingest/process item summary + embeddings run without network."""

    async def fake_embeddings(texts: list[str], **_: object) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    async def fake_summarize(text: str, **kwargs: object) -> SummaryResult:
        return SummaryResult(
            title="Снимок доски",
            summary="Краткое содержание распознанного текста.",
            key_points=["Ключевой пункт"],
            decisions=[],
            action_items=[],
            topics=["notes"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="neutral",
            highlights=[],
        )

    async def fake_moments(text: str, **kwargs: object) -> list:
        return []

    monkeypatch.setattr("app.core.item_ingest.generate_embeddings", fake_embeddings)
    monkeypatch.setattr("app.core.item_processing.generate_embeddings", fake_embeddings)
    monkeypatch.setattr("app.core.item_summary.summarize_content", fake_summarize)
    monkeypatch.setattr("app.core.item_summary.extract_key_moments", fake_moments)


def _stub_ocr(monkeypatch, text: str = "Распознанный текст с доски") -> None:
    async def fake_ocr(data: bytes, *, mime_type: str = "image/jpeg") -> str:
        return text

    monkeypatch.setattr(telegram_routes, "ocr_image", fake_ocr)


# ---------------------------------------------------------------------------
# _handle_photo_message (lines 3137-3257)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_photo_message_saves_item_and_replies(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-photo@example.com", 9101)
    capture = _Capture()
    capture.file = TelegramFile("file-id", "photos/board.jpg", 2048)
    capture.data = b"jpeg-bytes"
    _fake_item_pipeline(monkeypatch)
    _stub_ocr(monkeypatch)

    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 31, "chat": {"id": 9101}, "caption": "Доска после встречи"},
        account=account,
        photo={
            "kind": "photo",
            "file_id": "file-id",
            "file_unique_id": "uniq-1",
            "mime_type": "image/jpeg",
            "file_size": 2048,
        },
    )

    assert "Принял фото" in capture.messages[0]["text"]
    # Status message is removed once OCR completes.
    assert capture.deleted_messages == [{"chat_id": 9101, "message_id": 1}]
    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert item.kind == "image"
    assert "Доска после встречи" in item.body
    assert "Распознанный текст с доски" in item.body
    assert item.metadata_["telegram"]["file_unique_id"] == "uniq-1"
    assert item.metadata_["telegram"]["size"] == len(b"jpeg-bytes")
    assert account.active_context["ref_type"] == "item"
    assert account.active_context["ref_id"] == str(item.id)
    reply = capture.messages[-1]
    assert reply["parse_mode"] == "HTML"
    assert "Краткое содержание распознанного текста." in reply["text"]


@pytest.mark.asyncio
async def test_handle_photo_message_size_limit_edges(
    db_session: AsyncSession, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-photo-size@example.com", 9102)
    monkeypatch.setattr(telegram_routes.settings, "telegram_download_max_bytes", 16)
    message = {"message_id": 32, "chat": {"id": 9102}}

    # Declared file_size above the cap is rejected before any download.
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message=message,
        account=account,
        photo={"kind": "photo", "file_id": "file-id", "file_size": 17},
    )
    assert len(capture.messages) == 1
    assert "слишком большой" in capture.messages[0]["text"]

    # get_file reports an oversize file: status message sent, then cleaned up.
    capture = _Capture()
    capture.file = TelegramFile("file-id", "photos/p.jpg", 17)
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message=message,
        account=account,
        photo={"kind": "photo", "file_id": "file-id"},
    )
    assert "Принял фото" in capture.messages[0]["text"]
    assert "слишком большой" in capture.messages[-1]["text"]
    assert capture.deleted_messages == [{"chat_id": 9102, "message_id": 1}]

    # The download itself raises the too-large error.
    capture = _Capture()
    capture.file = TelegramFile("file-id", "photos/p.jpg", None)
    capture.data = b"x" * 17
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message=message,
        account=account,
        photo={"kind": "photo", "file_id": "file-id"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]
    assert capture.messages[-1]["reply_to_message_id"] == 32

    # A download that ignores the cap is still rejected by the length check.
    capture = _UncappedDownloadCapture()
    capture.file = TelegramFile("file-id", "photos/p.jpg", None)
    capture.data = b"x" * 17
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message=message,
        account=account,
        photo={"kind": "photo", "file_id": "file-id"},
    )
    assert "слишком большой" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_handle_photo_message_validation_and_ocr_edges(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-photo-edges@example.com", 9103)
    photo = {"kind": "photo", "file_id": "file-id", "mime_type": "image/jpeg"}

    # No chat id: nothing happens.
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session, capture, message={"message_id": 1}, account=account, photo=photo
    )
    assert capture.messages == []

    # file_id is not a string: silently ignored.
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 2, "chat": {"id": 9103}},
        account=account,
        photo={"kind": "photo", "file_id": None},
    )
    assert capture.messages == []

    # OCR failure is reported.
    async def fail_ocr(data: bytes, *, mime_type: str = "image/jpeg") -> str:
        raise OcrError("ocr backend down")

    monkeypatch.setattr(telegram_routes, "ocr_image", fail_ocr)
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 3, "chat": {"id": 9103}},
        account=account,
        photo=photo,
    )
    assert "Не смог распознать фото" in capture.messages[-1]["text"]
    assert capture.deleted_messages == [{"chat_id": 9103, "message_id": 1}]

    # Blank OCR output is reported as no recognizable content.
    _stub_ocr(monkeypatch, text="   \n ")
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 4, "chat": {"id": 9103}},
        account=account,
        photo=photo,
    )
    assert "не нашёл текста" in capture.messages[-1]["text"]

    # An inactive account is blocked before any download.
    user.account_status = "suspended"
    await db_session.flush()
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 5, "chat": {"id": 9103}},
        account=account,
        photo=photo,
    )
    assert len(capture.messages) == 1
    assert "не активен" in capture.messages[0]["text"]


@pytest.mark.asyncio
async def test_handle_photo_message_ingest_and_summary_failures(
    db_session: AsyncSession, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-photo-fail@example.com", 9104)
    _stub_ocr(monkeypatch)
    photo = {
        "kind": "photo",
        "file_id": "file-id",
        "file_unique_id": "uniq-fail",
        "mime_type": "image/jpeg",
    }

    async def fail_ingest(*args: object, **kwargs: object):
        raise RuntimeError("db down")

    monkeypatch.setattr(telegram_routes, "ingest_item", fail_ingest)
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 6, "chat": {"id": 9104}},
        account=account,
        photo=photo,
    )
    assert "Не смог сохранить фото" in capture.messages[-1]["text"]

    # Item saved, but summary generation fails.
    monkeypatch.undo()
    _stub_ocr(monkeypatch)
    _fake_item_pipeline(monkeypatch)

    async def fail_summary(*args: object, **kwargs: object):
        raise RuntimeError("summarizer down")

    monkeypatch.setattr(telegram_routes, "summarize_and_embed_item", fail_summary)
    capture = _Capture()
    await telegram_routes._handle_photo_message(
        db_session,
        capture,
        message={"message_id": 7, "chat": {"id": 9104}},
        account=account,
        photo=photo,
    )
    assert "Сохранил фото, но не смог" in capture.messages[-1]["text"]


# ---------------------------------------------------------------------------
# _handle_forwarded_text (lines 3527-3590) + _route_text_like dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_text_like_saves_forwarded_long_text(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-forward@example.com", 9201)
    _fake_item_pipeline(monkeypatch)
    capture = _Capture()
    text = "Заметка о продуктовой стратегии\n" + "х" * 450
    message = {
        "message_id": 41,
        "chat": {"id": 9201},
        "forward_origin": {"type": "user"},
        "text": text,
    }

    await telegram_routes._route_text_like(
        db_session, capture, message=message, account=account, text=text
    )

    assert "Сохраняю в материалы" in capture.messages[0]["text"]
    assert capture.deleted_messages == [{"chat_id": 9201, "message_id": 1}]
    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert item.kind == "note"
    assert item.source_ref == "telegram:text:9201:41"
    assert item.metadata_["telegram"]["forwarded"] is True
    assert "Заметка о продуктовой стратегии" in item.title
    chunks = (
        await db_session.execute(select(ItemChunk).where(ItemChunk.item_id == item.id))
    ).scalars().all()
    assert any("Краткое содержание распознанного текста." in c.content for c in chunks)
    assert account.active_context["ref_type"] == "item"
    assert account.active_context["ref_id"] == str(item.id)
    reply = capture.messages[-1]
    assert reply["parse_mode"] == "HTML"
    assert "Краткое содержание распознанного текста." in reply["text"]


@pytest.mark.asyncio
async def test_handle_forwarded_text_failure_paths(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-forward-fail@example.com", 9202)
    text = "Первая строка\n" + "y" * 450

    # No chat id: nothing happens.
    capture = _Capture()
    await telegram_routes._handle_forwarded_text(
        db_session, capture, message={"message_id": 1}, account=account, text=text
    )
    assert capture.messages == []

    # Ingest failure removes the status message and reports the error.
    async def fail_ingest(*args: object, **kwargs: object):
        raise RuntimeError("db down")

    monkeypatch.setattr(telegram_routes, "ingest_item", fail_ingest)
    capture = _Capture()
    await telegram_routes._handle_forwarded_text(
        db_session,
        capture,
        message={"message_id": 42, "chat": {"id": 9202}},
        account=account,
        text=text,
    )
    assert "Не смог сохранить текст" in capture.messages[-1]["text"]
    assert capture.deleted_messages == [{"chat_id": 9202, "message_id": 1}]

    # Saved, but summary generation fails.
    monkeypatch.undo()
    _fake_item_pipeline(monkeypatch)

    async def fail_summary(*args: object, **kwargs: object):
        raise RuntimeError("summarizer down")

    monkeypatch.setattr(telegram_routes, "summarize_and_embed_item", fail_summary)
    capture = _Capture()
    await telegram_routes._handle_forwarded_text(
        db_session,
        capture,
        message={"message_id": 43, "chat": {"id": 9202}},
        account=account,
        text=text,
    )
    assert "Сохранил текст, но не смог" in capture.messages[-1]["text"]

    # An inactive account is blocked before saving anything.
    user.account_status = "suspended"
    await db_session.flush()
    capture = _Capture()
    await telegram_routes._handle_forwarded_text(
        db_session,
        capture,
        message={"message_id": 44, "chat": {"id": 9202}},
        account=account,
        text=text,
    )
    assert len(capture.messages) == 1
    assert "не активен" in capture.messages[0]["text"]


@pytest.mark.asyncio
async def test_route_text_like_dispatches_url_messages(
    db_session: AsyncSession, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-url-route@example.com", 9203)
    seen: list[str] = []

    async def fake_url_handler(db, client, *, message, account, url):
        seen.append(url)

    monkeypatch.setattr(telegram_routes, "_handle_url_message", fake_url_handler)
    capture = _Capture()
    await telegram_routes._route_text_like(
        db_session,
        capture,
        message={"message_id": 45, "chat": {"id": 9203}},
        account=account,
        text="глянь https://example.com/a",
    )
    assert seen == ["https://example.com/a"]
    assert capture.messages == []


# ---------------------------------------------------------------------------
# _format_pending_actions_for_run (lines 2693-2719)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_query_consent_dispatch_provisions_account(
    db_session: AsyncSession,
):
    capture = _Capture()
    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cb-consent",
            "from": {"id": 911001, "first_name": "New", "language_code": "ru"},
            "data": telegram_routes.CONSENT_CALLBACK_DATA,
            "message": {"message_id": 7, "chat": {"id": 911001}},
        },
    )

    assert capture.callback_answers == [{"id": "cb-consent", "text": "Готово!"}]
    assert capture.edited_messages
    assert "Аккаунт WaiComputer создан" in capture.edited_messages[0]["text"]
    account = (
        await db_session.execute(
            select(TelegramAccount).where(TelegramAccount.telegram_user_id == 911001)
        )
    ).scalar_one()
    assert account.telegram_chat_id == 911001


@pytest.mark.asyncio
async def test_callback_query_delete_dispatch_removes_user(db_session: AsyncSession):
    user, _account = await _linked_account(db_session, "tg-cb-delete@example.com", 911002)
    user_id = user.id
    capture = _Capture()

    await telegram_routes._handle_callback_query(
        db_session,
        capture,
        callback_query={
            "id": "cb-del",
            "from": {"id": 911002},
            "data": telegram_routes.DELETE_CALLBACK_DATA,
            "message": {"message_id": 9, "chat": {"id": 911002}},
        },
    )

    assert capture.callback_answers == [{"id": "cb-del", "text": "Удалено."}]
    assert capture.edited_messages
    assert "удалены" in capture.edited_messages[0]["text"]
    assert await db_session.get(User, user_id) is None


# ---------------------------------------------------------------------------
# _handle_email_command edges (2249, 2252, 2255-2260, 2276-2283)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_command_validation_and_send_failure(
    db_session: AsyncSession, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-email@example.com", 911003)

    # No chat id: nothing happens.
    capture = _Capture()
    await telegram_routes._handle_email_command(
        db_session, capture, message={"message_id": 1}, account=account, arg="a@b.com"
    )
    assert capture.messages == []

    # Malformed address gets the usage hint.
    capture = _Capture()
    await telegram_routes._handle_email_command(
        db_session,
        capture,
        message={"message_id": 2, "chat": {"id": 911003}},
        account=account,
        arg="not-an-email",
    )
    assert "Формат: /email" in capture.messages[-1]["text"]

    # SMTP failure is surfaced; the address is never attached.
    async def fail_send(*args: object, **kwargs: object):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.core.email.send_email_verification_email", fail_send)
    capture = _Capture()
    await telegram_routes._handle_email_command(
        db_session,
        capture,
        message={"message_id": 3, "chat": {"id": 911003}},
        account=account,
        arg="new@example.com",
    )
    assert "Не удалось отправить письмо" in capture.messages[-1]["text"]

    # Inactive accounts are blocked before validation.
    user.account_status = "suspended"
    await db_session.flush()
    capture = _Capture()
    await telegram_routes._handle_email_command(
        db_session,
        capture,
        message={"message_id": 4, "chat": {"id": 911003}},
        account=account,
        arg="new@example.com",
    )
    assert len(capture.messages) == 1
    assert "не активен" in capture.messages[0]["text"]


# ---------------------------------------------------------------------------
# _resume_agent_after_telegram_action (2000, 2003-2007, 2017-2032)
# ---------------------------------------------------------------------------


class _AgentlessSession:
    """Delegates to the real session but pretends the Agent row is gone."""

    def __init__(self, inner: AsyncSession) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get(self, model: Any, pk: Any) -> Any:
        if model is Agent:
            return None
        return await self._inner.get(model, pk)


@pytest.mark.asyncio
async def test_resume_agent_after_action_missing_run_and_agent(
    db_session: AsyncSession,
):
    user, _account = await _linked_account(db_session, "tg-resume-miss@example.com", 9401)

    # Unknown run id: a silent no-op.
    await telegram_routes._resume_agent_after_telegram_action(
        db_session, SimpleNamespace(agent_run_id=uuid4())
    )

    # Run exists but its agent is gone: the run is failed explicitly.
    _agent, run = await _agent_with_run(db_session, user)
    await telegram_routes._resume_agent_after_telegram_action(
        _AgentlessSession(db_session), SimpleNamespace(agent_run_id=run.id)
    )
    assert run.status == "failed"
    assert run.error == "Agent not found"
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_resume_agent_after_action_dispatches_child_runs(
    db_session: AsyncSession, monkeypatch
):
    user, _account = await _linked_account(db_session, "tg-resume-ok@example.com", 9402)
    agent, run = await _agent_with_run(db_session, user)
    child = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"child:{uuid4().hex}",
        trigger_kind="manual",
    )
    db_session.add(child)
    await db_session.flush()
    run_id, child_id = run.id, child.id

    calls: dict[str, Any] = {}

    async def fake_run_job(db, target_run_id, *, planner, executor):
        calls["run_id"] = target_run_id
        calls["planner"] = planner
        calls["executor"] = executor

    monkeypatch.setattr(telegram_routes, "run_job", fake_run_job)
    monkeypatch.setattr(telegram_routes, "planner_for_agent", lambda a: "fake-planner")
    monkeypatch.setattr(
        telegram_routes, "pop_agent_runs_to_dispatch_after_commit", lambda db: [child_id]
    )
    enqueued: list[Any] = []
    monkeypatch.setattr(telegram_routes, "enqueue_agent_run", enqueued.append)

    await telegram_routes._resume_agent_after_telegram_action(
        db_session, SimpleNamespace(agent_run_id=run_id)
    )

    assert calls == {
        "run_id": run_id,
        "planner": "fake-planner",
        "executor": telegram_routes.execute_agent_step,
    }
    assert enqueued == [child_id]


@pytest.mark.asyncio
async def test_resume_agent_after_action_surfaces_dispatch_error(
    db_session: AsyncSession, monkeypatch
):
    user, _account = await _linked_account(db_session, "tg-resume-err@example.com", 9403)
    agent, run = await _agent_with_run(db_session, user)
    child = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"child:{uuid4().hex}",
        trigger_kind="manual",
    )
    db_session.add(child)
    await db_session.flush()
    run_id, child_id = run.id, child.id

    async def fake_run_job(db, target_run_id, *, planner, executor):
        return None

    def fail_enqueue(target_run_id):
        raise AgentDispatchError("Could not start agent run")

    monkeypatch.setattr(telegram_routes, "run_job", fake_run_job)
    monkeypatch.setattr(telegram_routes, "planner_for_agent", lambda a: "fake-planner")
    monkeypatch.setattr(
        telegram_routes, "pop_agent_runs_to_dispatch_after_commit", lambda db: [child_id]
    )
    monkeypatch.setattr(telegram_routes, "enqueue_agent_run", fail_enqueue)

    with pytest.raises(AgentDispatchError):
        await telegram_routes._resume_agent_after_telegram_action(
            db_session, SimpleNamespace(agent_run_id=run_id)
        )

    failed_child = (
        await db_session.execute(select(AgentRun).where(AgentRun.id == child_id))
    ).scalar_one()
    assert failed_child.status == "failed"
    assert failed_child.error == "Could not start agent run"
    assert failed_child.finished_at is not None
