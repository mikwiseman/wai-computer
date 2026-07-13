"""🎧 Озвучить: the TTS button on summary replies — keyboard shape, callback
routing through the durable summary-audio artifact pipeline, and chat delivery.
All bot I/O is captured in-memory — zero real network."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core.summary_audio import SummaryAudioError
from app.models.recording import Recording, RecordingStatus, Summary
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from tests.test_telegram_agent_commands import (  # reuse the shared harness
    _Capture,
    _linked_account,
)


class _AudioCapture(_Capture):
    """Fake client that also records sendAudio calls."""

    def __init__(self) -> None:
        super().__init__()
        self.audios: list[dict[str, Any]] = []

    async def send_audio(
        self,
        chat_id: int,
        *,
        filename: str,
        data: bytes,
        title: str | None = None,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        self.audios.append(
            {
                "chat_id": chat_id,
                "filename": filename,
                "data": data,
                "title": title,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"message_id": 777}


def test_keyboards_carry_tts_button():
    kb = telegram_routes._recording_reply_keyboard("https://wai.computer/share/x", "rid-1")
    rows = kb["inline_keyboard"]
    assert rows[0][0]["url"] == "https://wai.computer/share/x"
    assert rows[1][0]["callback_data"] == "tts:rec:rid-1"
    # No share link -> TTS row alone; no id and no link -> no keyboard at all.
    only_tts = telegram_routes._recording_reply_keyboard(None, "rid-2")
    assert only_tts["inline_keyboard"][0][0]["callback_data"] == "tts:rec:rid-2"
    assert telegram_routes._recording_reply_keyboard(None, None) is None

    item_kb = telegram_routes._item_reply_keyboard("iid-1")
    assert item_kb["inline_keyboard"][0][0]["callback_data"] == "tts:item:iid-1"
    assert "🎧" in item_kb["inline_keyboard"][0][0]["text"]


async def _seed_ready_recording(db: AsyncSession, user_id) -> Recording:
    rec = Recording(
        user_id=user_id,
        title="Планёрка",
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db.add(rec)
    await db.flush()
    db.add(Summary(recording_id=rec.id, summary="Обсудили запуск.", key_points=[]))
    await db.flush()
    return rec


def _artifact(
    user_id,
    rec_id,
    *,
    status: str,
    storage_path: str | None = None,
    task_id: str | None = None,
) -> SummaryAudioArtifact:
    return SummaryAudioArtifact(
        user_id=user_id,
        recording_id=rec_id,
        item_id=None,
        source_kind="recording",
        status=status,
        stage="completed" if status == "succeeded" else "queued",
        progress_percent=100 if status == "succeeded" else 0,
        summary_hash="h" * 64,
        input_char_count=10,
        provider="xai",
        model="xai-text-to-speech",
        voice_id="ara",
        language="auto",
        storage_path=storage_path,
        task_id=task_id,
    )


async def _tts_callback(db, capture, account, data: str) -> None:
    await telegram_routes._handle_tts_callback(
        db,
        capture,
        account=account,
        callback_id="cb-1",
        chat_id=9601,
        reply_to_message_id=55,
        data=data,
    )


@pytest.mark.asyncio
async def test_tts_callback_reuses_succeeded_artifact_and_sends_audio(
    db_session, monkeypatch, tmp_path
):
    user, account = await _linked_account(db_session, "tg-tts-1@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)
    audio_file = tmp_path / f"{uuid4()}.mp3"
    audio_file.write_bytes(b"ID3-mp3-bytes")
    artifact = _artifact(
        user.id, rec.id, status=SummaryAudioStatus.SUCCEEDED.value,
        storage_path=str(audio_file),
    )

    async def fake_start(db, *, source_kind, source_id, user_id):
        assert source_kind == "recording"
        assert source_id == rec.id
        assert user_id == user.id
        return artifact

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", fake_start)
    monkeypatch.setattr(
        telegram_routes, "resolve_summary_audio_file_path", lambda a: audio_file
    )

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert capture.callback_answers[-1]["text"] == "Отправляю аудио"
    assert len(capture.audios) == 1
    sent = capture.audios[0]
    assert sent["data"] == b"ID3-mp3-bytes"
    assert sent["title"] == "Планёрка"
    assert sent["filename"].endswith(".mp3")
    assert sent["reply_to_message_id"] == 55


@pytest.mark.asyncio
async def test_tts_callback_enqueues_generation_when_queued(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-tts-2@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)
    artifact = _artifact(user.id, rec.id, status=SummaryAudioStatus.QUEUED.value)
    db_session.add(artifact)
    await db_session.flush()

    async def fake_start(db, *, source_kind, source_id, user_id):
        return artifact

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", fake_start)

    enqueued: list[dict[str, Any]] = []

    class _FakeAsyncResult:
        id = "task-123"

    def fake_delay(**kwargs):
        enqueued.append(kwargs)
        return _FakeAsyncResult()

    monkeypatch.setattr(
        "app.tasks.telegram_summary_audio.deliver_summary_audio_telegram_task.delay",
        fake_delay,
    )

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert enqueued == [
        {
            "artifact_id": str(artifact.id),
            "chat_id": 9601,
            "reply_to_message_id": 55,
        }
    ]
    assert artifact.task_id == "task-123"
    assert "Готовлю аудио" in capture.callback_answers[-1]["text"]
    assert capture.audios == []


@pytest.mark.asyncio
async def test_tts_callback_running_artifact_says_in_progress(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-tts-3@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)
    artifact = _artifact(
        user.id, rec.id, status=SummaryAudioStatus.RUNNING.value, task_id="busy"
    )

    async def fake_start(db, *, source_kind, source_id, user_id):
        return artifact

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", fake_start)

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert "уже готовится" in capture.callback_answers[-1]["text"]
    assert capture.audios == []


@pytest.mark.asyncio
async def test_tts_callback_surfaces_artifact_errors(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-tts-4@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)

    async def failing_start(db, *, source_kind, source_id, user_id):
        raise SummaryAudioError(
            code="summary_missing",
            message="Summary has not been generated.",
            status_code=404,
        )

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", failing_start)

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert capture.callback_answers[-1]["text"] == "Не получилось"
    assert "Озвучить не получится" in capture.messages[-1]["text"]
    assert capture.audios == []


@pytest.mark.asyncio
async def test_tts_callback_ignores_malformed_data(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-tts-5@example.com", 9601)

    async def unexpected_start(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("malformed tts callbacks must not hit the artifact layer")

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", unexpected_start)

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, "tts:rec:not-a-uuid")
    await _tts_callback(db_session, capture, account, "tts:nope:" + str(uuid4()))

    assert capture.audios == []
    assert len(capture.callback_answers) == 2


@pytest.mark.asyncio
async def test_tts_callback_enqueue_failure_is_honest(db_session, monkeypatch):
    user, account = await _linked_account(db_session, "tg-tts-6@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)
    artifact = _artifact(user.id, rec.id, status=SummaryAudioStatus.QUEUED.value)
    db_session.add(artifact)
    await db_session.flush()

    async def fake_start(db, *, source_kind, source_id, user_id):
        return artifact

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", fake_start)

    def broken_delay(**kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(
        "app.tasks.telegram_summary_audio.deliver_summary_audio_telegram_task.delay",
        broken_delay,
    )

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert artifact.status == SummaryAudioStatus.FAILED.value
    assert artifact.error_code == "summary_audio_enqueue_failed"
    assert capture.callback_answers[-1]["text"] == "Не получилось"
    assert any("Не смог запустить озвучку" in m["text"] for m in capture.messages)


@pytest.mark.asyncio
async def test_tts_callback_succeeded_but_file_missing_is_honest(
    db_session, monkeypatch
):
    user, account = await _linked_account(db_session, "tg-tts-7@example.com", 9601)
    rec = await _seed_ready_recording(db_session, user.id)
    artifact = _artifact(
        user.id, rec.id, status=SummaryAudioStatus.SUCCEEDED.value, storage_path=None
    )

    async def fake_start(db, *, source_kind, source_id, user_id):
        return artifact

    monkeypatch.setattr(telegram_routes, "start_summary_audio_artifact", fake_start)

    def missing_file(a):
        raise SummaryAudioError(
            code="summary_audio_file_missing",
            message="Audio file is missing.",
            status_code=404,
        )

    monkeypatch.setattr(
        telegram_routes, "resolve_summary_audio_file_path", missing_file
    )

    capture = _AudioCapture()
    await _tts_callback(db_session, capture, account, f"tts:rec:{rec.id}")

    assert any("отправить не вышло" in m["text"] for m in capture.messages)
    assert capture.audios == []
