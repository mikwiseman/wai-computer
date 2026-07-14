"""Direct tests for the Telegram summary-audio delivery Celery task: the
wrapper contract (timeout anomaly, failure logging, no retries) and every
``_run`` branch — generate→persist→deliver, reuse-without-generate, artifact
gone, generation failure notifies the sender, delivery failure notifies the
sender. Zero real network."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summary_audio import SummaryAudioError
from app.core.telegram_client import TelegramClientError
from app.core.xai_tts import XaiTTSError
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from app.models.user import User
from app.tasks import telegram_summary_audio


def _coro_factory(*, raises: Exception | None = None):
    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises

    return _inner


def test_task_timeout_captures_anomaly() -> None:
    with (
        patch.object(
            telegram_summary_audio,
            "_run",
            _coro_factory(raises=SoftTimeLimitExceeded()),
        ),
        patch.object(telegram_summary_audio, "capture_sentry_anomaly") as anomaly,
    ):
        with pytest.raises(SoftTimeLimitExceeded):
            telegram_summary_audio.deliver_summary_audio_telegram_task(
                artifact_id=str(uuid4()), chat_id=1
            )
    anomaly.assert_called_once()


def test_task_failure_logs_and_raises() -> None:
    with patch.object(
        telegram_summary_audio, "_run", _coro_factory(raises=ValueError("boom"))
    ):
        with pytest.raises(ValueError):
            telegram_summary_audio.deliver_summary_audio_telegram_task(
                artifact_id=str(uuid4()), chat_id=1
            )


def test_task_success_runs_clean() -> None:
    with patch.object(telegram_summary_audio, "_run", _coro_factory()):
        telegram_summary_audio.deliver_summary_audio_telegram_task(
            artifact_id=str(uuid4()), chat_id=1
        )


class _Client:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.actions: list[str] = []
        self.edited_markups: list[dict[str, Any]] = []
        self.send_failures = 0

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict:
        if self.send_failures:
            self.send_failures -= 1
            raise TelegramClientError("telegram down")
        self.messages.append({"chat_id": chat_id, "text": text})
        return {"message_id": 1}

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.actions.append(action)

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> dict:
        self.edited_markups.append(
            {"message_id": message_id, "reply_markup": reply_markup}
        )
        return {"message_id": message_id}


async def _seed_artifact(
    db: AsyncSession, *, status: str = SummaryAudioStatus.SUCCEEDED.value
) -> SummaryAudioArtifact:
    user = User(email=f"tts-task-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    artifact = SummaryAudioArtifact(
        user_id=user.id,
        recording_id=None,
        item_id=None,
        source_kind="recording",
        status=status,
        stage="completed",
        progress_percent=100,
        summary_hash="h" * 64,
        input_char_count=10,
        provider="xai",
        model="xai-text-to-speech",
        voice_id="ara",
        language="auto",
    )
    # The DB check constraint wants recording XOR item; use a raw recording row.
    from app.models.recording import Recording, RecordingStatus

    rec = Recording(
        user_id=user.id, title="t", type="note", status=RecordingStatus.READY.value
    )
    db.add(rec)
    await db.flush()
    artifact.recording_id = rec.id
    db.add(artifact)
    await db.flush()
    return artifact


def _ctx(db_session):
    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    return fake_ctx


@pytest.mark.asyncio
async def test_run_generates_persists_and_delivers(db_session, monkeypatch):
    artifact = await _seed_artifact(db_session)
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    payload = SimpleNamespace(artifact_id=artifact.id)
    calls: list[str] = []

    async def fake_prepare(db, *, artifact_id, task_id):
        calls.append("prepare")
        return payload

    async def fake_generate(p):
        assert p is payload
        calls.append("generate")
        return SimpleNamespace(audio=b"mp3")

    async def fake_persist(db, *, artifact_id, result):
        calls.append("persist")

    delivered: list[dict[str, Any]] = []

    async def fake_deliver(db, cl, *, artifact, chat_id, reply_to_message_id):
        delivered.append(
            {"artifact_id": artifact.id, "chat_id": chat_id, "reply": reply_to_message_id}
        )

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        telegram_summary_audio, "generate_summary_audio_for_payload", fake_generate
    )
    monkeypatch.setattr(
        telegram_summary_audio, "persist_summary_audio_generation_result", fake_persist
    )
    monkeypatch.setattr(
        "app.api.routes.telegram.deliver_summary_audio_to_telegram", fake_deliver
    )

    await telegram_summary_audio._run(
        artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=7, task_id="t1"
    )

    assert calls == ["prepare", "generate", "persist"]
    assert delivered == [{"artifact_id": artifact.id, "chat_id": 42, "reply": 7}]
    assert client.messages == []


@pytest.mark.asyncio
async def test_run_reuses_succeeded_artifact_without_generating(db_session, monkeypatch):
    artifact = await _seed_artifact(db_session)
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return None  # already claimed/succeeded elsewhere

    async def unexpected_generate(p):  # pragma: no cover - guard
        raise AssertionError("must not generate when payload is None")

    delivered: list[Any] = []

    async def fake_deliver(db, cl, *, artifact, chat_id, reply_to_message_id):
        delivered.append(artifact.id)

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        telegram_summary_audio, "generate_summary_audio_for_payload", unexpected_generate
    )
    monkeypatch.setattr(
        "app.api.routes.telegram.deliver_summary_audio_to_telegram", fake_deliver
    )

    await telegram_summary_audio._run(
        artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=None, task_id="t2"
    )
    assert delivered == [artifact.id]


@pytest.mark.asyncio
async def test_run_drops_when_artifact_gone(db_session, monkeypatch):
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return None

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )

    await telegram_summary_audio._run(
        artifact_id=str(uuid4()), chat_id=42, reply_to_message_id=None, task_id="t3"
    )
    assert client.messages == []


@pytest.mark.asyncio
async def test_run_skips_delivery_when_not_succeeded(db_session, monkeypatch):
    artifact = await _seed_artifact(
        db_session, status=SummaryAudioStatus.FAILED.value
    )
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return None

    async def unexpected_deliver(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("must not deliver a non-succeeded artifact")

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        "app.api.routes.telegram.deliver_summary_audio_to_telegram", unexpected_deliver
    )

    await telegram_summary_audio._run(
        artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=None, task_id="t4"
    )
    assert client.messages == []


@pytest.mark.asyncio
async def test_run_generation_failure_fails_job_and_notifies(db_session, monkeypatch):
    artifact = await _seed_artifact(db_session, status=SummaryAudioStatus.QUEUED.value)
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return SimpleNamespace(artifact_id=artifact.id)

    async def failing_generate(p):
        raise XaiTTSError(code="xai_down", message="xAI is down")

    failed: list[dict[str, Any]] = []

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed.append({"code": error_code})

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        telegram_summary_audio, "generate_summary_audio_for_payload", failing_generate
    )
    monkeypatch.setattr(
        telegram_summary_audio, "fail_summary_audio_generation_job", fake_fail
    )

    with pytest.raises(XaiTTSError):
        await telegram_summary_audio._run(
            artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=None, task_id="t5"
        )
    assert failed == [{"code": "xai_down"}]
    assert any("Озвучить саммари не получилось" in m["text"] for m in client.messages)


@pytest.mark.asyncio
async def test_run_unexpected_generation_failure_notifies(db_session, monkeypatch):
    artifact = await _seed_artifact(db_session, status=SummaryAudioStatus.QUEUED.value)
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return SimpleNamespace(artifact_id=artifact.id)

    async def failing_generate(p):
        raise RuntimeError("disk full")

    failed: list[str] = []

    async def fake_fail(db, *, artifact_id, error_code, error_message):
        failed.append(error_code)

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        telegram_summary_audio, "generate_summary_audio_for_payload", failing_generate
    )
    monkeypatch.setattr(
        telegram_summary_audio, "fail_summary_audio_generation_job", fake_fail
    )
    monkeypatch.setattr(
        telegram_summary_audio, "capture_sentry_exception", lambda exc: None
    )

    with pytest.raises(RuntimeError):
        await telegram_summary_audio._run(
            artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=None, task_id="t6"
        )
    assert failed == ["summary_audio_generation_failed"]
    assert len(client.messages) == 1


@pytest.mark.asyncio
async def test_run_delivery_failure_notifies_and_raises(db_session, monkeypatch):
    artifact = await _seed_artifact(db_session)
    client = _Client()
    monkeypatch.setattr(telegram_summary_audio, "get_db_context", _ctx(db_session))
    monkeypatch.setattr(telegram_summary_audio, "TelegramBotClient", lambda: client)

    async def fake_prepare(db, *, artifact_id, task_id):
        return None

    async def failing_deliver(db, cl, *, artifact, chat_id, reply_to_message_id):
        raise SummaryAudioError(
            code="summary_audio_file_missing",
            message="Audio file is missing.",
            status_code=404,
        )

    monkeypatch.setattr(
        telegram_summary_audio, "prepare_summary_audio_generation_payload", fake_prepare
    )
    monkeypatch.setattr(
        "app.api.routes.telegram.deliver_summary_audio_to_telegram", failing_deliver
    )

    with pytest.raises(SummaryAudioError):
        await telegram_summary_audio._run(
            artifact_id=str(artifact.id), chat_id=42, reply_to_message_id=None, task_id="t7"
        )
    assert any("отправить не вышло" in m["text"] for m in client.messages)


@pytest.mark.asyncio
async def test_notify_swallows_telegram_errors(monkeypatch):
    client = _Client()
    client.send_failures = 1
    await telegram_summary_audio._notify(client, 42, "hello")
    assert client.messages == []
