"""End-to-end integration test for the full recording lifecycle.

Covers: create -> save transcript -> generate summary -> search -> export ->
        star -> soft delete -> verify trash -> restore -> permanent delete.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.core.summarizer import SummaryResult


@pytest.mark.asyncio
async def test_full_recording_lifecycle(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Walk through every major recording operation in a single linear flow."""

    # ------------------------------------------------------------------ #
    # Step 1: Create a recording via the API
    # ------------------------------------------------------------------ #
    create_resp = await client.post(
        "/api/recordings",
        headers=auth_headers,
        json={"title": None, "type": "meeting", "language": "en"},
    )
    assert create_resp.status_code == 201
    recording = create_resp.json()
    recording_id = recording["id"]
    assert recording["type"] == "meeting"
    assert recording["status"] == "pending_upload"
    assert recording["title"] is None
    assert recording["starred_at"] is None

    # ------------------------------------------------------------------ #
    # Step 2: Save a live transcript (simulates streaming segments)
    # ------------------------------------------------------------------ #
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_embeddings",
        AsyncMock(side_effect=lambda texts, **_: [[0.1] * 1536 for _ in texts]),
    )
    monkeypatch.setattr(
        "app.api.routes.recordings.generate_title",
        AsyncMock(return_value="Quarterly Planning Session"),
    )

    transcript_resp = await client.post(
        f"/api/recordings/{recording_id}/transcript",
        headers=auth_headers,
        json={
            "duration_seconds": 45,
            "segments": [
                {
                    "text": "Welcome everyone to the quarterly planning session.",
                    "speaker": "Speaker 1",
                    "start_ms": 0,
                    "end_ms": 5000,
                    "confidence": 0.97,
                },
                {
                    "text": "Let's review the product roadmap and budget allocations.",
                    "speaker": "Speaker 2",
                    "start_ms": 5000,
                    "end_ms": 12000,
                    "confidence": 0.94,
                },
                {
                    "text": "We need to finalize the marketing strategy by next Friday.",
                    "speaker": "Speaker 1",
                    "start_ms": 12000,
                    "end_ms": 20000,
                    "confidence": 0.96,
                },
            ],
        },
    )
    assert transcript_resp.status_code == 200
    transcript_data = transcript_resp.json()
    assert transcript_data["status"] == "ready"
    assert transcript_data["title"] == "Quarterly Planning Session"
    assert len(transcript_data["segments"]) == 3
    assert transcript_data["segments"][0]["content"] == (
        "Welcome everyone to the quarterly planning session."
    )

    # Verify the transcript via the detail endpoint
    detail_resp = await client.get(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["title"] == "Quarterly Planning Session"
    assert len(detail["segments"]) == 3

    # ------------------------------------------------------------------ #
    # Step 3: Generate AI summary (with mocked model)
    # ------------------------------------------------------------------ #
    async def fake_summarize_transcript(_transcript: str, **kwargs) -> SummaryResult:
        return SummaryResult(
            title="Quarterly Planning Session",
            summary="Team discussed Q2 product roadmap and agreed on budget allocations.",
            key_points=[
                "Roadmap reviewed and approved",
                "Marketing strategy deadline set to Friday",
            ],
            decisions=[
                {"decision": "Approve Q2 budget", "context": "Finance review"},
            ],
            action_items=[
                {
                    "task": "Finalize marketing strategy",
                    "owner": "Speaker 1",
                    "due": "2026-03-25",
                    "priority": "high",
                },
            ],
            topics=["roadmap", "budget", "marketing"],
            people_mentioned=["Speaker 1", "Speaker 2"],
            follow_up_questions=["What is the contingency plan?"],
            sentiment="positive",
        )

    monkeypatch.setattr(
        "app.api.routes.recordings.summarize_transcript",
        fake_summarize_transcript,
    )

    summary_resp = await client.post(
        f"/api/recordings/{recording_id}/generate-summary",
        headers=auth_headers,
    )
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert summary_data["summary"] is not None
    assert "roadmap" in summary_data["summary"].lower()

    # Verify summary via GET
    summary_get_resp = await client.get(
        f"/api/recordings/{recording_id}/summary",
        headers=auth_headers,
    )
    assert summary_get_resp.status_code == 200
    summary_get = summary_get_resp.json()
    assert "budget" in summary_get["summary"].lower()

    # Verify action items were persisted on the recording detail
    detail_after_summary = await client.get(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
    )
    assert detail_after_summary.status_code == 200
    assert len(detail_after_summary.json()["action_items"]) == 1
    assert detail_after_summary.json()["action_items"][0]["task"] == "Finalize marketing strategy"

    # ------------------------------------------------------------------ #
    # Step 4: Search for the recording (fulltext search)
    # ------------------------------------------------------------------ #
    fts_resp = await client.get(
        "/api/search/fts",
        headers=auth_headers,
        params={"q": "quarterly planning"},
    )
    assert fts_resp.status_code == 200
    fts_payload = fts_resp.json()
    assert fts_payload["total"] >= 1
    matched_recording_ids = {r["recording_id"] for r in fts_payload["results"]}
    assert recording_id in matched_recording_ids

    # ------------------------------------------------------------------ #
    # Step 5: Export as markdown
    # ------------------------------------------------------------------ #
    export_resp = await client.get(
        f"/api/recordings/{recording_id}/export",
        headers=auth_headers,
        params={"format": "markdown"},
    )
    assert export_resp.status_code == 200
    assert "text/markdown" in export_resp.headers["content-type"]
    export_body = export_resp.text
    assert "# Quarterly Planning Session" in export_body
    assert "## Summary" in export_body
    assert "budget" in export_body.lower()
    assert "## Transcript" in export_body
    assert "Welcome everyone" in export_body
    assert "Quarterly_Planning_Session.md" in export_resp.headers["content-disposition"]

    # ------------------------------------------------------------------ #
    # Step 6: Star the recording
    # ------------------------------------------------------------------ #
    star_resp = await client.post(
        f"/api/recordings/{recording_id}/star",
        headers=auth_headers,
    )
    assert star_resp.status_code == 200
    assert star_resp.json()["starred_at"] is not None

    # Confirm it shows up in starred filter
    starred_list_resp = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"starred": "true"},
    )
    assert starred_list_resp.status_code == 200
    starred_ids = [r["id"] for r in starred_list_resp.json()]
    assert recording_id in starred_ids

    # ------------------------------------------------------------------ #
    # Step 7: Soft-delete (move to trash)
    # ------------------------------------------------------------------ #
    delete_resp = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
    )
    assert delete_resp.status_code == 204

    # Should disappear from active list
    active_list_resp = await client.get(
        "/api/recordings",
        headers=auth_headers,
    )
    assert active_list_resp.status_code == 200
    active_ids = [r["id"] for r in active_list_resp.json()]
    assert recording_id not in active_ids

    # ------------------------------------------------------------------ #
    # Step 8: Verify it's in trash
    # ------------------------------------------------------------------ #
    trash_resp = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"trashed": "true"},
    )
    assert trash_resp.status_code == 200
    trashed_ids = [r["id"] for r in trash_resp.json()]
    assert recording_id in trashed_ids
    trashed_rec = next(r for r in trash_resp.json() if r["id"] == recording_id)
    assert trashed_rec["deleted_at"] is not None

    # Should also be excluded from search results
    fts_after_trash = await client.get(
        "/api/search/fts",
        headers=auth_headers,
        params={"q": "quarterly planning"},
    )
    assert fts_after_trash.status_code == 200
    trashed_search_ids = {r["recording_id"] for r in fts_after_trash.json()["results"]}
    assert recording_id not in trashed_search_ids

    # ------------------------------------------------------------------ #
    # Step 9: Restore from trash
    # ------------------------------------------------------------------ #
    restore_resp = await client.post(
        f"/api/recordings/{recording_id}/restore",
        headers=auth_headers,
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    # Should reappear in active list
    restored_list_resp = await client.get(
        "/api/recordings",
        headers=auth_headers,
    )
    assert restored_list_resp.status_code == 200
    restored_ids = [r["id"] for r in restored_list_resp.json()]
    assert recording_id in restored_ids

    # Should reappear in search results
    fts_after_restore = await client.get(
        "/api/search/fts",
        headers=auth_headers,
        params={"q": "quarterly planning"},
    )
    assert fts_after_restore.status_code == 200
    restored_search_ids = {r["recording_id"] for r in fts_after_restore.json()["results"]}
    assert recording_id in restored_search_ids

    # ------------------------------------------------------------------ #
    # Step 10: Permanently delete
    # ------------------------------------------------------------------ #
    # First soft-delete again
    soft_delete_2 = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
    )
    assert soft_delete_2.status_code == 204

    # Then permanent delete
    perm_delete = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
        params={"permanent": "true"},
    )
    assert perm_delete.status_code == 204

    # Should be completely gone -- not in active, not in trash, not by detail
    gone_detail = await client.get(
        f"/api/recordings/{recording_id}",
        headers=auth_headers,
    )
    assert gone_detail.status_code == 404

    gone_trash = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"trashed": "true"},
    )
    assert gone_trash.status_code == 200
    assert recording_id not in [r["id"] for r in gone_trash.json()]

    gone_active = await client.get(
        "/api/recordings",
        headers=auth_headers,
    )
    assert gone_active.status_code == 200
    assert recording_id not in [r["id"] for r in gone_active.json()]
