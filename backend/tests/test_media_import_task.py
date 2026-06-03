"""Direct tests for the uploaded-media Celery task (``app.tasks.media_import``).

The task body only runs via ``.delay`` in production, so the success /
permanent-failure / retry / timeout paths and the staged-file lifecycle need
explicit coverage. The inner ``_import`` coroutine runs against the test DB
with ``import_media_as_recording`` stubbed (no ffmpeg/Deepgram).
"""

from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core import recording_import
from app.core.recording_import import RecordingImportError
from app.models.recording import Recording
from app.models.user import User
from app.tasks import media_import


def _coro_factory(*, raises: Exception | None = None):
    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises

    return _inner


# --- wrapper: staged-file lifecycle -----------------------------------------


def test_media_import_task_success_unlinks_staged(tmp_path) -> None:
    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"data")
    with patch.object(media_import, "_import", _coro_factory()):
        media_import.import_uploaded_media_task(
            user_id=str(uuid4()),
            staged_path=str(staged),
            filename="clip.mp4",
            content_type="video/mp4",
        )
    assert not staged.exists()  # success drops the staged original


def test_media_import_task_permanent_failure_unlinks_and_raises(tmp_path) -> None:
    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"data")
    with (
        patch.object(media_import, "_import", _coro_factory(raises=ValueError("bad file"))),
        patch.object(media_import, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(ValueError):
            media_import.import_uploaded_media_task(
                user_id=str(uuid4()), staged_path=str(staged)
            )
    cap.assert_called_once()
    assert not staged.exists()  # a non-retryable failure cleans up too


def test_media_import_task_retryable_keeps_staged(tmp_path) -> None:
    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"data")

    class _RetryError(Exception):
        pass

    # A transient error must trigger self.retry and NOT delete the staged file.
    with (
        patch.object(
            media_import, "_import", _coro_factory(raises=ConnectionError("flaky"))
        ),
        patch.object(media_import, "is_retryable_exception", return_value=True),
        patch.object(media_import, "capture_sentry_exception"),
        patch.object(media_import.import_uploaded_media_task, "retry", side_effect=_RetryError()),
    ):
        with pytest.raises(_RetryError):
            media_import.import_uploaded_media_task(
                user_id=str(uuid4()), staged_path=str(staged)
            )
    assert staged.exists()  # kept for the next attempt


def test_media_import_task_timeout_captures_anomaly(tmp_path) -> None:
    from billiard.exceptions import SoftTimeLimitExceeded

    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"data")
    with (
        patch.object(
            media_import, "_import", _coro_factory(raises=SoftTimeLimitExceeded())
        ),
        patch.object(media_import, "capture_sentry_anomaly") as anomaly,
    ):
        with pytest.raises(SoftTimeLimitExceeded):
            media_import.import_uploaded_media_task(
                user_id=str(uuid4()), staged_path=str(staged)
            )
    anomaly.assert_called_once()


# --- inner _import coroutine -------------------------------------------------


@pytest.mark.asyncio
async def test_import_calls_recording_pipeline(db_session, monkeypatch, tmp_path) -> None:
    user = User(email=f"media-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"video-bytes")

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    captured: dict = {}

    async def fake_import(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(media_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(media_import, "import_media_as_recording", fake_import)

    await media_import._import(
        user_id=str(user.id),
        staged_path=str(staged),
        filename="clip.mp4",
        content_type="video/mp4",
        title="My clip",
        language="en",
    )
    assert captured["data"] == b"video-bytes"
    assert captured["source_label"] == "upload"
    assert captured["title"] == "My clip"
    assert captured["user"].id == user.id


@pytest.mark.asyncio
async def test_import_uses_precreated_recording(db_session, monkeypatch, tmp_path) -> None:
    user = User(email=f"media-existing-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="clip",
        type="note",
        status="processing",
    )
    db_session.add(recording)
    await db_session.flush()

    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"video-bytes")

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    captured: dict = {}

    async def fake_import(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(media_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(media_import, "import_media_as_recording", fake_import)

    await media_import._import(
        user_id=str(user.id),
        recording_id=str(recording.id),
        staged_path=str(staged),
        filename="clip.mp4",
        content_type="video/mp4",
        title=None,
        language="en",
    )

    assert captured["recording"].id == recording.id


@pytest.mark.asyncio
async def test_precreated_recording_is_failed_when_normalization_rejects_media(
    db_session, monkeypatch
) -> None:
    user = User(email=f"media-normalize-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title="clip",
        type="note",
        status="processing",
    )
    db_session.add(recording)
    await db_session.flush()
    recording_id = recording.id
    await db_session.commit()

    async def reject_media(*args, **kwargs):
        raise RecordingImportError("bad_media", "Bad media file.")

    monkeypatch.setattr(
        recording_import,
        "_normalize_media_for_transcription",
        reject_media,
    )

    with pytest.raises(RecordingImportError):
        await recording_import.import_media_as_recording(
            db=db_session,
            user=user,
            data=b"video-bytes",
            filename="clip.mp4",
            content_type="video/mp4",
            title=None,
            source_label="upload",
            recording=recording,
        )

    failed = await db_session.get(Recording, recording_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_code == "bad_media"
    assert failed.failure_message == "Bad media file."


@pytest.mark.asyncio
async def test_import_user_gone_skips_pipeline(db_session, monkeypatch, tmp_path) -> None:
    staged = tmp_path / "clip.mp4"
    staged.write_bytes(b"x")

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    called = False

    async def fake_import(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(media_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(media_import, "import_media_as_recording", fake_import)

    await media_import._import(
        user_id=str(uuid4()),  # no such user
        staged_path=str(staged),
        filename="clip.mp4",
        content_type="video/mp4",
        title=None,
        language=None,
    )
    assert called is False  # no user -> pipeline never invoked
