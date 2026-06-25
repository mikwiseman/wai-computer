"""Coverage push for app/api/routes/recordings.py — remaining route bodies.

Targets: related recordings with embeddings (2456-2524), summary-audio routes
(2685-2796), summary-generation state (2806-2818), assign-speaker (2917-2978),
rematch (2998-3026), save_transcript failure paths (2595-2621), celery enqueue
wrappers (1140-1174), export highlight sections (1797-1811, 1857-1877), and the
summary-generation status messages (533-542).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

import app.api.routes.recordings as recordings_module
from app.models.highlight import Highlight
from app.models.recording import (
    Recording,
    RecordingStatus,
    Segment,
    Summary,
    SummaryGenerationStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Coverage Recording",
    type_: str = "note",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


def _summary_row(recording_id, summary: str = "Weekly sync summary.", topics=None) -> Summary:
    return Summary(
        recording_id=recording_id,
        summary=summary,
        key_points=["Key point one"],
        decisions=None,
        topics=topics,
        people_mentioned=None,
        sentiment=None,
    )


def _segment_row(recording_id, content: str, *, embedding=None, speaker=None) -> Segment:
    return Segment(
        recording_id=recording_id,
        content=content,
        speaker=speaker,
        raw_label=speaker,
        start_ms=0,
        end_ms=2000,
        confidence=None,
        embedding=embedding,
    )


# ---------------------------------------------------------------------------
# Pure helpers: summary-generation status copy + celery enqueue wrappers
# ---------------------------------------------------------------------------


def test_summary_generation_message_variants():
    msg = recordings_module._summary_generation_message
    assert msg("not_started", "") == "Summary has not been generated."
    assert msg(SummaryGenerationStatus.QUEUED.value, "queued") == (
        "Summary generation is queued."
    )
    assert msg(SummaryGenerationStatus.QUEUED.value, "waiting_for_transcript") == (
        "Summary generation will start when the transcript is ready."
    )
    running = SummaryGenerationStatus.RUNNING.value
    assert msg(running, "preparing_transcript") == (
        "Preparing transcript for summary generation."
    )
    assert msg(running, "saving_summary") == "Saving generated summary."
    assert msg(running, "calling_model") == "Generating summary."
    assert msg(SummaryGenerationStatus.SUCCEEDED.value, "done") == "Summary is ready."
    assert msg(SummaryGenerationStatus.FAILED.value, "failed") == (
        "Summary generation failed."
    )
    assert msg("mystery", "stage") == "Summary generation status is unknown."


@pytest.mark.asyncio
async def test_enqueue_wrappers_send_celery_tasks(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def fake_send_task(name, kwargs=None, **_extra):
        sent.append((name, kwargs or {}))
        return SimpleNamespace(id=f"task-{len(sent)}")

    monkeypatch.setattr("app.tasks.celery_app.celery_app.send_task", fake_send_task)

    await recordings_module.enqueue_recording_audio_processing(
        recording_id=uuid4(),
        user_id=uuid4(),
        staged_path=recordings_module.Path("/tmp/staged.mp3"),
        content_type="audio/mpeg",
        user_default_language="en",
    )
    audio_task_id = recordings_module.enqueue_summary_audio_generation(uuid4())

    assert sent[0][0] == (
        "app.tasks.recording_audio_processing.process_staged_recording_upload"
    )
    assert sent[1][0] == "app.tasks.summary_audio_generation.generate_summary_audio"
    assert audio_task_id == "task-2"


# ---------------------------------------------------------------------------
# Export sections: highlights in markdown and txt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_markdown_renders_highlight_variants(
    client: AsyncClient, auth_headers: dict, db_session
):
    rec = await _create_recording(client, auth_headers, title="Highlights MD")
    rec_id = UUID(rec["id"])
    db_session.add(_segment_row(rec_id, "Alpha update from the team.", speaker="S1"))
    db_session.add_all(
        [
            Highlight(
                recording_id=rec_id,
                category="decision",
                title="Approved budget",
                speaker="S1",
                start_ms=1000,
                end_ms=2000,
            ),
            Highlight(
                recording_id=rec_id,
                category="action",
                title="Send the offer",
                speaker=None,
                start_ms=3000,
                end_ms=4000,
            ),
            Highlight(
                recording_id=rec_id,
                category="insight",
                title="Untimed insight",
                speaker=None,
                start_ms=None,
                end_ms=None,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{rec_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert response.status_code == 200
    body = response.text
    assert "## Key Highlights" in body
    assert "**[Decision]** Approved budget (S1, 0:01)" in body
    assert "**[Action]** Send the offer (0:03)" in body
    assert "**[Insight]** Untimed insight" in body


@pytest.mark.asyncio
async def test_export_txt_renders_summary_and_highlights(
    client: AsyncClient, auth_headers: dict, db_session
):
    rec = await _create_recording(client, auth_headers, title="Highlights TXT")
    rec_id = UUID(rec["id"])
    db_session.add(_segment_row(rec_id, "Beta planning discussion.", speaker="S1"))
    db_session.add(_summary_row(rec_id, summary="Planning went well."))
    db_session.add_all(
        [
            Highlight(
                recording_id=rec_id,
                category="decision",
                title="Ship beta",
                speaker="S1",
                start_ms=500,
                end_ms=900,
            ),
            Highlight(
                recording_id=rec_id,
                category="question",
                title="Timeline question",
                speaker=None,
                start_ms=1500,
                end_ms=None,
            ),
            Highlight(
                recording_id=rec_id,
                category="insight",
                title="No timing data",
                speaker=None,
                start_ms=None,
                end_ms=None,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{rec_id}/export",
        headers=auth_headers,
        params={"format": "txt"},
    )
    assert response.status_code == 200
    body = response.text
    assert "Planning went well." in body
    assert "- [Decision] Ship beta (" in body
    assert "- [Question] Timeline question (0:01)" in body
    assert "- [Insight] No timing data" in body


# ---------------------------------------------------------------------------
# Related recordings via pgvector centroid (2456-2524)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_related_recordings_ranks_by_embedding_similarity(
    client: AsyncClient, auth_headers: dict, db_session
):
    source = await _create_recording(client, auth_headers, title="Source memo")
    similar = await _create_recording(client, auth_headers, title="Similar memo")
    source_id, similar_id = UUID(source["id"]), UUID(similar["id"])

    near = [0.1] * 1536
    db_session.add_all(
        [
            _segment_row(source_id, "Roadmap planning for Atlas.", embedding=near),
            _segment_row(source_id, "Atlas budget detail.", embedding=near),
            _segment_row(similar_id, "Atlas follow-up discussion.", embedding=near),
        ]
    )
    db_session.add(_summary_row(similar_id, topics=["Atlas", "Budget"]))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{source_id}/related",
        headers=auth_headers,
        params={"limit": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recording_id"] == str(source_id)
    related = data["related"]
    assert [item["id"] for item in related] == [str(similar_id)]
    assert related[0]["similarity_score"] == pytest.approx(1.0, abs=1e-3)
    assert related[0]["matching_topic"] == "Atlas"


# ---------------------------------------------------------------------------
# Summary audio routes (2685-2796)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_summary_audio_state_not_started(
    client: AsyncClient, auth_headers: dict, db_session
):
    rec = await _create_recording(client, auth_headers, title="Audio state")
    rec_id = UUID(rec["id"])
    db_session.add(_summary_row(rec_id))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{rec_id}/summary/audio", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_started"
    assert data["source_id"] == str(rec_id)


@pytest.mark.asyncio
async def test_get_summary_audio_requires_summary(
    client: AsyncClient, auth_headers: dict
):
    rec = await _create_recording(client, auth_headers, title="No summary yet")
    response = await client.get(
        f"/api/recordings/{rec['id']}/summary/audio", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Summary not generated"


@pytest.mark.asyncio
async def test_start_summary_audio_enqueues_generation(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Audio start")
    rec_id = UUID(rec["id"])
    db_session.add(_summary_row(rec_id))
    await db_session.flush()

    monkeypatch.setattr(
        recordings_module,
        "enqueue_summary_audio_generation",
        lambda artifact_id: f"audio-task-{artifact_id}",
    )

    response = await client.post(
        f"/api/recordings/{rec_id}/summary/audio", headers=auth_headers
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert data["source_id"] == str(rec_id)


@pytest.mark.asyncio
async def test_start_summary_audio_without_summary_fails(
    client: AsyncClient, auth_headers: dict
):
    rec = await _create_recording(client, auth_headers, title="Audio no summary")
    response = await client.post(
        f"/api/recordings/{rec['id']}/summary/audio", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_start_summary_audio_enqueue_failure_returns_503(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Audio enqueue fail")
    rec_id = UUID(rec["id"])
    db_session.add(_summary_row(rec_id))
    await db_session.flush()

    def boom(_artifact_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(recordings_module, "enqueue_summary_audio_generation", boom)

    response = await client.post(
        f"/api/recordings/{rec_id}/summary/audio", headers=auth_headers
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to start summary audio generation"


@pytest.mark.asyncio
async def test_summary_audio_file_missing_artifact_404(
    client: AsyncClient, auth_headers: dict, db_session
):
    rec = await _create_recording(client, auth_headers, title="Audio file missing")
    rec_id = UUID(rec["id"])
    db_session.add(_summary_row(rec_id))
    await db_session.flush()

    response = await client.get(
        f"/api/recordings/{rec_id}/summary/audio/file", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Summary audio has not been created."


@pytest.mark.asyncio
async def test_summary_generation_state_not_started(
    client: AsyncClient, auth_headers: dict
):
    rec = await _create_recording(client, auth_headers, title="Gen state")
    response = await client.get(
        f"/api/recordings/{rec['id']}/summary-generation", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_started"
    assert data["message"] == "Summary has not been generated."


# ---------------------------------------------------------------------------
# Assign speaker (2917-2978)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_speaker_requires_exactly_one_target(
    client: AsyncClient, auth_headers: dict
):
    rec = await _create_recording(client, auth_headers, title="Assign validation")
    response = await client.post(
        f"/api/recordings/{rec['id']}/assign-speaker",
        headers=auth_headers,
        json={"raw_label": "S1"},
    )
    assert response.status_code == 400

    response = await client.post(
        f"/api/recordings/{rec['id']}/assign-speaker",
        headers=auth_headers,
        json={
            "raw_label": "S1",
            "person_id": str(uuid4()),
            "new_display_name": "Anna",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_assign_speaker_unknown_recording_and_person(
    client: AsyncClient, auth_headers: dict
):
    response = await client.post(
        f"/api/recordings/{uuid4()}/assign-speaker",
        headers=auth_headers,
        json={"raw_label": "S1", "new_display_name": "Anna"},
    )
    assert response.status_code == 404

    rec = await _create_recording(client, auth_headers, title="Assign 404 person")
    response = await client.post(
        f"/api/recordings/{rec['id']}/assign-speaker",
        headers=auth_headers,
        json={"raw_label": "S1", "person_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Person not found"


@pytest.mark.asyncio
async def test_assign_speaker_creates_person_and_confirms_segments(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Assign new person")
    rec_id = UUID(rec["id"])
    segment = Segment(
        recording_id=rec_id,
        content="Hello from the unnamed speaker.",
        speaker="Speaker 1",
        raw_label="S1",
        start_ms=0,
        end_ms=1500,
        confidence=None,
        auto_assigned=True,
        match_confidence=0.4,
    )
    db_session.add(segment)
    await db_session.flush()

    monkeypatch.setattr(
        recordings_module,
        "store_voiceprint_from_recording_speaker",
        AsyncMock(return_value=None),
    )

    response = await client.post(
        f"/api/recordings/{rec_id}/assign-speaker",
        headers=auth_headers,
        json={"raw_label": "S1", "new_display_name": "Anna Kovach"},
    )
    assert response.status_code == 200

    await db_session.refresh(segment)
    assert segment.person_id is not None
    assert segment.auto_assigned is False
    assert segment.match_confidence is None

    # Re-assign the same cluster to the now-existing person via person_id.
    response = await client.post(
        f"/api/recordings/{rec_id}/assign-speaker",
        headers=auth_headers,
        json={"raw_label": "S1", "person_id": str(segment.person_id)},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Rematch speakers (2998-3026)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rematch_speakers_paths(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    response = await client.post(
        f"/api/recordings/{uuid4()}/rematch", headers=auth_headers
    )
    assert response.status_code == 404

    rec = await _create_recording(client, auth_headers, title="Rematch")

    monkeypatch.setattr(
        recordings_module, "rematch_recording_speakers", AsyncMock(return_value=None)
    )
    response = await client.post(
        f"/api/recordings/{rec['id']}/rematch", headers=auth_headers
    )
    assert response.status_code == 422

    monkeypatch.setattr(
        recordings_module,
        "rematch_recording_speakers",
        AsyncMock(return_value=SimpleNamespace(updated_clusters=2, matched_clusters=1)),
    )
    response = await client.post(
        f"/api/recordings/{rec['id']}/rematch", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "recording_id": rec["id"],
        "updated_clusters": 2,
        "matched_clusters": 1,
    }


# ---------------------------------------------------------------------------
# save_transcript failure paths (2595-2621)
# ---------------------------------------------------------------------------

_TRANSCRIPT_PAYLOAD = {
    "duration_seconds": 4,
    "segments": [
        {
            "text": "Failure path segment",
            "speaker": "S1",
            "start_ms": 0,
            "end_ms": 4000,
            "confidence": 0.9,
        }
    ],
}


@pytest.mark.asyncio
async def test_save_transcript_validation_error_marks_recording_failed(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Transcript fail")
    # Persist the recording row so the route's rollback() cannot undo it and the
    # failure-marking path has a row to update.
    await db_session.commit()
    monkeypatch.setattr(
        recordings_module,
        "_persist_client_segments",
        AsyncMock(side_effect=HTTPException(status_code=422, detail="Segments rejected")),
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/transcript",
        headers=auth_headers,
        json=_TRANSCRIPT_PAYLOAD,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Segments rejected"

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(Recording).where(Recording.id == UUID(rec["id"]))
        )
    ).scalar_one()
    assert row.status == "failed"
    assert row.failure_code == "transcript_validation_failed"


@pytest.mark.asyncio
async def test_mark_recording_failed_by_id_keeps_ready_recording_terminal(
    client: AsyncClient, auth_headers: dict, db_session
):
    rec = await _create_recording(client, auth_headers, title="Ready terminal")
    row = (
        await db_session.execute(select(Recording).where(Recording.id == UUID(rec["id"])))
    ).scalar_one()
    row.status = RecordingStatus.READY.value
    row.failure_code = None
    row.failure_message = None
    await db_session.commit()

    await recordings_module._mark_recording_failed_by_id(
        UUID(rec["id"]),
        db_session,
        "late_transcript_save_failed",
        "Late transcript save failed after ready.",
    )

    db_session.expire_all()
    refreshed = (
        await db_session.execute(select(Recording).where(Recording.id == UUID(rec["id"])))
    ).scalar_one()
    assert refreshed.status == RecordingStatus.READY.value
    assert refreshed.failure_code is None
    assert refreshed.failure_message is None


@pytest.mark.asyncio
async def test_save_transcript_validation_error_when_marking_also_fails(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Transcript mark fail")
    monkeypatch.setattr(
        recordings_module,
        "_persist_client_segments",
        AsyncMock(side_effect=HTTPException(status_code=422, detail="Segments rejected")),
    )
    monkeypatch.setattr(
        recordings_module,
        "_mark_recording_failed_by_id",
        AsyncMock(side_effect=RuntimeError("db gone")),
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/transcript",
        headers=auth_headers,
        json=_TRANSCRIPT_PAYLOAD,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_save_transcript_unexpected_error_returns_500(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    rec = await _create_recording(client, auth_headers, title="Transcript crash")
    monkeypatch.setattr(
        recordings_module,
        "_persist_client_segments",
        AsyncMock(side_effect=RuntimeError("storage exploded")),
    )
    monkeypatch.setattr(
        recordings_module,
        "_mark_recording_failed_by_id",
        AsyncMock(side_effect=RuntimeError("db gone")),
    )

    response = await client.post(
        f"/api/recordings/{rec['id']}/transcript",
        headers=auth_headers,
        json=_TRANSCRIPT_PAYLOAD,
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save transcript"
