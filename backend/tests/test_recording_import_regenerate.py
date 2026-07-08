"""Tests for regenerate_recording_summary (the Telegram retry path)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_import import (
    RecordingImportError,
    regenerate_recording_summary,
)
from app.core.summarizer import SummaryResult
from app.models.person import Person
from app.models.recording import (
    ActionItem,
    Recording,
    RecordingStatus,
    Segment,
    Summary,
)
from app.models.user import User


def _summary_result(title: str = "Созвон по Сколково") -> SummaryResult:
    return SummaryResult(
        title=title,
        summary="**Итог:** решили подавать заявку до `пятницы`.",
        key_points=["Заявка до пятницы"],
        decisions=[{"decision": "Подать заявку", "context": "грант"}],
        action_items=[{"task": "Подготовить аннотацию", "owner": "Мик"}],
        topics=["гранты"],
        people_mentioned=["Мик"],
        follow_up_questions=[],
        sentiment="positive",
        highlights=[],
    )


async def _seed_recording(db: AsyncSession, *, title: str | None) -> tuple[User, Recording]:
    user = User(email="regen@example.com", password_hash="hash")
    db.add(user)
    await db.flush()
    recording = Recording(
        user_id=user.id,
        title=title,
        type="meeting",
        status=RecordingStatus.READY.value,
        duration_seconds=300,
    )
    db.add(recording)
    await db.flush()
    person = Person(user_id=user.id, display_name="Дмитрий Рубин")
    db.add(person)
    await db.flush()
    db.add_all(
        [
            Segment(
                recording_id=recording.id,
                speaker="speaker_0",
                raw_label="speaker_0",
                person_id=person.id,
                content="Давайте зафиксируем обновление.",
                start_ms=0,
                end_ms=4_000,
                confidence=0.95,
            ),
            Segment(
                recording_id=recording.id,
                speaker="speaker_1",
                raw_label="speaker_1",
                content="С нашей стороны нет вопросов.",
                start_ms=4_500,
                end_ms=7_000,
                confidence=0.9,
            ),
        ]
    )
    await db.commit()
    return user, recording


@pytest.mark.asyncio
async def test_regenerate_creates_summary_and_backfills_title(db_session: AsyncSession):
    user, recording = await _seed_recording(db_session, title=None)

    summarize = AsyncMock(return_value=_summary_result())
    with patch("app.core.recording_import.summarize_transcript", summarize):
        summary, speaker_names = await regenerate_recording_summary(
            db_session,
            recording=recording,
            user=user,
        )

    assert summary.summary.startswith("**Итог:**")
    assert recording.title == "Созвон по Сколково"
    assert speaker_names == {"speaker_0": "Дмитрий Рубин"}
    # The labeled transcript fed to the summarizer uses the resolved name.
    transcript_arg = summarize.await_args.args[0]
    assert "Дмитрий Рубин: Давайте зафиксируем обновление." in transcript_arg
    action_items = (
        (
            await db_session.execute(
                select(ActionItem).where(ActionItem.recording_id == recording.id)
            )
        )
        .scalars()
        .all()
    )
    assert [a.task for a in action_items] == ["Подготовить аннотацию"]


@pytest.mark.asyncio
async def test_regenerate_replaces_generated_keeps_manual_and_title(
    db_session: AsyncSession,
):
    user, recording = await _seed_recording(db_session, title="Existing Title")
    db_session.add_all(
        [
            Summary(recording_id=recording.id, summary="old", sentiment="neutral"),
            ActionItem(
                recording_id=recording.id,
                task="Старое сгенерированное",
                source="generated",
            ),
            ActionItem(
                recording_id=recording.id,
                task="Ручное — не трогать",
                source="manual",
            ),
        ]
    )
    await db_session.commit()
    await db_session.refresh(recording)

    with patch(
        "app.core.recording_import.summarize_transcript",
        AsyncMock(return_value=_summary_result(title="New Title")),
    ):
        summary, _ = await regenerate_recording_summary(
            db_session,
            recording=recording,
            user=user,
        )

    assert recording.title == "Existing Title"  # explicit titles survive
    assert summary.summary.startswith("**Итог:**")
    tasks = {
        (a.task, a.source)
        for a in (
            await db_session.execute(
                select(ActionItem).where(ActionItem.recording_id == recording.id)
            )
        )
        .scalars()
        .all()
    }
    assert tasks == {
        ("Подготовить аннотацию", "generated"),
        ("Ручное — не трогать", "manual"),
    }


@pytest.mark.asyncio
async def test_regenerate_without_segments_raises(db_session: AsyncSession):
    user = User(email="regen-empty@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.READY.value,
    )
    db_session.add(recording)
    await db_session.commit()

    with pytest.raises(RecordingImportError, match="нет транскрипта") as excinfo:
        await regenerate_recording_summary(db_session, recording=recording, user=user)
    assert excinfo.value.code == "no_transcript"
