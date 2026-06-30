"""API tests for the universal /items routes (Phase 1).

Background summarization is disabled in these tests by stubbing the Celery
task's ``.delay`` (the route imports it lazily), so we assert the synchronous
capture + feed + detail behaviour without a broker or OpenAI.
"""

import zipfile
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.routes.items import (
    _derive_status,
    _item_error,
    enqueue_summary_audio_generation,
)
from app.models.item import Item, ItemSummary
from app.models.recording import Recording
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from tests.conftest import LEGAL_ACCEPTANCE

pytestmark = pytest.mark.asyncio


def _docx_bytes(text: str) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
        zf.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        )
    return buf.getvalue()


async def _register_headers(client) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": f"items-folder-{uuid4().hex}@example.com",
            "password": "testpassword123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code in (200, 201), response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_folder(client, headers: dict[str, str], name: str = "Materials") -> dict:
    response = await client.post("/api/folders", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def _fake_embeddings(texts: list[str], **_: object) -> list[list[float]]:
    return [[0.0] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.core.item_ingest.generate_embeddings", _fake_embeddings)


async def test_create_item_requires_body_or_url(client, auth_headers) -> None:
    resp = await client.post("/api/items", json={"source": "paste"}, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.parametrize("target", ["missing", "other_user"])
async def test_create_item_rejects_unknown_or_other_user_folder_id(
    client, auth_headers, target: str
) -> None:
    if target == "missing":
        folder_id = str(uuid4())
    else:
        other_headers = await _register_headers(client)
        folder_id = (await _create_folder(client, other_headers, name="Other User"))["id"]

    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        resp = await client.post(
            "/api/items",
            json={
                "source": "url",
                "kind": "article",
                "url": "https://example.com/private-folder-contract",
                "folder_id": folder_id,
            },
            headers=auth_headers,
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Folder not found"


async def test_create_item_paste_and_fetch_detail(client, auth_headers) -> None:
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay"
    ) as delay:
        resp = await client.post(
            "/api/items",
            json={
                "source": "paste",
                "kind": "note",
                "title": "My note",
                "body": "A paragraph about solar energy and storage economics.",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "My note"
    assert data["state"] == "raw"
    item_id = data["id"]
    # Background summarization was enqueued (not run inline).
    delay.assert_called_once()

    # Detail round-trips.
    detail = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == item_id


async def test_create_item_is_idempotent(client, auth_headers) -> None:
    payload = {"source": "paste", "title": "Dup", "body": "same content here"}
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        first = await client.post("/api/items", json=payload, headers=auth_headers)
        second = await client.post("/api/items", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get("/api/items", headers=auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


async def test_list_items_filters_by_kind(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "article", "body": "article body one"},
            headers=auth_headers,
        )
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "note body two"},
            headers=auth_headers,
        )
    articles = await client.get("/api/items?kind=article", headers=auth_headers)
    assert articles.status_code == 200
    data = articles.json()
    assert data["total"] == 1
    assert data["items"][0]["kind"] == "article"


async def test_items_scoped_to_user(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "body": "private to user A"},
            headers=auth_headers,
        )
    item_id = created.json()["id"]

    # A different user cannot read it.
    from uuid import uuid4

    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"other-{uuid4().hex}@example.com",
            "password": "testpassword123",
            "accepted_legal_terms": True,
            "legal_terms_version": "2026-05-22",
            "legal_privacy_version": "2026-05-22",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    denied = await client.get(f"/api/items/{item_id}", headers=other_headers)
    assert denied.status_code == 404


async def test_delete_item_soft_deletes(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "body": "to be deleted"},
            headers=auth_headers,
        )
    item_id = created.json()["id"]
    deleted = await client.delete(f"/api/items/{item_id}", headers=auth_headers)
    assert deleted.status_code == 204
    gone = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert gone.status_code == 404
    listing = await client.get("/api/items", headers=auth_headers)
    assert listing.json()["total"] == 0


async def test_derive_status_covers_every_state() -> None:
    assert _derive_status(Item(state="needs_input"), False) == "needs_input"
    assert _derive_status(Item(state="failed"), False) == "failed"
    assert (
        _derive_status(
            Item(state="raw", metadata_={"processing_error": {"code": "x", "message": "y"}}),
            False,
        )
        == "failed"
    )
    assert _derive_status(Item(state="raw", body="hello"), True) == "ready"
    assert _derive_status(Item(state="promoted", body="x"), True) == "ready"
    assert (
        _derive_status(Item(state="raw", url="https://e.com", body=None), False) == "fetching"
    )
    assert (
        _derive_status(Item(state="raw", body="has body", url=None), False) == "summarizing"
    )


async def test_item_error_surfaces_fetch_and_processing_errors() -> None:
    assert _item_error(Item(metadata_=None)) is None
    assert _item_error(Item(metadata_={})) is None
    fe = _item_error(
        Item(
            metadata_={
                "fetch_error": {"code": "youtube_no_transcript", "message": "Share the file"}
            }
        )
    )
    assert fe is not None and fe.code == "youtube_no_transcript"
    pe = _item_error(
        Item(metadata_={"processing_error": {"code": "enqueue_failed", "message": "Retry"}})
    )
    assert pe is not None and pe.code == "enqueue_failed"


async def test_create_item_exposes_summarizing_status(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        resp = await client.post(
            "/api/items",
            json={"source": "paste", "body": "notes on solar storage economics"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "summarizing"
    assert data["error"] is None


async def test_create_item_enqueue_failure_is_visible_not_swallowed(
    client, auth_headers
) -> None:
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await client.post(
            "/api/items",
            json={"source": "paste", "body": "this item cannot be enqueued"},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["state"] == "failed"
    assert data["status"] == "failed"
    assert data["error"]["code"] == "enqueue_failed"

    # The failure is also visible in the unified feed (not silently dropped).
    listing = await client.get("/api/items", headers=auth_headers)
    entry = next(e for e in listing.json()["items"] if e["id"] == data["id"])
    assert entry["status"] == "failed"
    assert entry["error"]["code"] == "enqueue_failed"


# --- POST /items/upload (document upload) ---


async def test_upload_markdown_creates_note_item_and_enqueues_summary(
    client, auth_headers
) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("notes.md", b"# Solar\n\nCosts fell sharply.", "text/markdown")},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["kind"] == "note"
    assert data["title"] == "notes"
    assert data["status"] == "summarizing"
    delay.assert_called_once()


@pytest.mark.parametrize("target", ["missing", "other_user"])
async def test_upload_item_rejects_unknown_or_other_user_folder_id(
    client, auth_headers, monkeypatch, target: str
) -> None:
    if target == "missing":
        folder_id = str(uuid4())
    else:
        other_headers = await _register_headers(client)
        folder_id = (await _create_folder(client, other_headers, name="Other Uploads"))["id"]

    monkeypatch.setattr("app.core.item_ingest.generate_embeddings", _fake_embeddings)
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        resp = await client.post(
            "/api/items/upload",
            data={"folder_id": folder_id},
            files={
                "file": (
                    "foldered.md",
                    b"# Foldered\n\nThis item must not land in an invalid folder.",
                    "text/markdown",
                )
            },
            headers=auth_headers,
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Folder not found"


async def test_upload_pdf_extracts_text(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"), patch(
        "app.core.document_extract._extract_pdf_text",
        return_value="Extracted PDF body about GPUs and inference cost.",
    ):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("GPU Paper.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["kind"] == "pdf"
    assert data["title"] == "GPU Paper"


async def test_upload_scanned_pdf_without_text_is_422(client, auth_headers) -> None:
    from app.core.source_fetch import SourceFetchError

    with patch(
        "app.core.document_extract._extract_pdf_text",
        side_effect=SourceFetchError("This PDF has no extractable text.", code="pdf_no_text"),
    ):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("scan.pdf", b"%PDF-1.4 scanned", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "no extractable text" in resp.json()["detail"].lower()


async def test_upload_scanned_pdf_ocrs_via_vision(client, auth_headers) -> None:
    # A no-text-layer PDF is OCR'd by the vision LLM instead of being rejected.
    from unittest.mock import AsyncMock

    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"), patch(
        "app.core.document_extract._extract_pdf_text", return_value=""
    ), patch("app.core.document_extract._pdf_page_count", return_value=2), patch(
        "app.core.ocr.ocr_pdf", new=AsyncMock(return_value="OCR'd scanned text about GPUs.")
    ):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("scan.pdf", b"%PDF-1.4 scanned", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "pdf"


async def test_upload_scanned_pdf_too_long_is_422(client, auth_headers) -> None:
    with patch("app.core.document_extract._extract_pdf_text", return_value=""), patch(
        "app.core.document_extract._pdf_page_count", return_value=999
    ):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("huge.pdf", b"%PDF-1.4 scanned", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "too long" in resp.json()["detail"].lower()


async def test_upload_scanned_pdf_ocr_yields_nothing_is_422(client, auth_headers) -> None:
    from unittest.mock import AsyncMock

    with patch("app.core.document_extract._extract_pdf_text", return_value=""), patch(
        "app.core.document_extract._pdf_page_count", return_value=1
    ), patch("app.core.ocr.ocr_pdf", new=AsyncMock(return_value="")):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("blank.pdf", b"%PDF-1.4 scanned", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "no readable text" in resp.json()["detail"].lower()


async def test_upload_video_enqueues_recording(client, auth_headers, db_session) -> None:
    # Video is no longer rejected — it's staged and handed to the recording pipeline.
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42 body", "video/mp4")},
            headers=auth_headers,
        )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["kind"] == "recording"
    assert data["status"] == "processing"
    assert data["recording_id"]
    delay.assert_called_once()
    kwargs = delay.call_args.kwargs
    assert kwargs["recording_id"] == data["recording_id"]
    assert kwargs["filename"] == "clip.mp4"
    assert kwargs["content_type"] == "video/mp4"
    assert kwargs["staged_path"].endswith(".mp4")
    recording = (
        await db_session.execute(
            select(Recording).where(Recording.id == UUID(data["recording_id"]))
        )
    ).scalar_one()
    assert recording.status == "processing"
    assert recording.title == "clip"


async def test_upload_media_with_valid_folder_creates_foldered_recording(
    client, auth_headers, db_session
) -> None:
    folder = await _create_folder(client, auth_headers, name="Media Imports")

    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            data={"folder_id": folder["id"]},
            files={"file": ("memo.mp3", b"ID3\x03\x00\x00\x00 audio bytes", "audio/mpeg")},
            headers=auth_headers,
        )

    assert resp.status_code == 202, resp.text
    recording_id = resp.json()["recording_id"]
    delay.assert_called_once()
    recording = (
        await db_session.execute(select(Recording).where(Recording.id == UUID(recording_id)))
    ).scalar_one()
    assert str(recording.folder_id) == folder["id"]


async def test_upload_audio_enqueues_recording(client, auth_headers) -> None:
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("memo.mp3", b"ID3\x03\x00\x00\x00 audio bytes", "audio/mpeg")},
            headers=auth_headers,
        )
    assert resp.status_code == 202, resp.text
    assert resp.json()["recording_id"]
    delay.assert_called_once()
    assert delay.call_args.kwargs["recording_id"] == resp.json()["recording_id"]
    assert delay.call_args.kwargs["staged_path"].endswith(".mp3")


async def test_upload_rejects_truly_unsupported_type(client, auth_headers) -> None:
    resp = await client.post(
        "/api/items/upload",
        files={"file": ("malware.exe", b"MZ\x90\x00 binary", "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 415


async def test_upload_empty_media_is_400(client, auth_headers) -> None:
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("empty.mp4", b"", "video/mp4")},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    delay.assert_not_called()


async def test_upload_media_enqueue_failure_is_503(client, auth_headers) -> None:
    # No-fallback: a broker outage surfaces as 503, and the staged file is dropped.
    with patch(
        "app.tasks.media_import.import_uploaded_media_task.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("clip.mov", b"\x00\x00\x00\x14ftypqt  video", "video/quicktime")},
            headers=auth_headers,
        )
    assert resp.status_code == 503


async def test_upload_media_too_large_is_413(client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_max_bytes", 8)
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("big.mp4", b"\x00\x00\x00\x18ftypmp42 way over eight", "video/mp4")},
            headers=auth_headers,
        )
    assert resp.status_code == 413
    delay.assert_not_called()


async def test_upload_empty_file_is_400(client, auth_headers) -> None:
    resp = await client.post(
        "/api/items/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_upload_non_utf8_text_is_422(client, auth_headers) -> None:
    resp = await client.post(
        "/api/items/upload",
        files={"file": ("bad.txt", b"\xff\xfe\x00bad bytes", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_upload_too_large_is_413(client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_max_bytes", 8)
    resp = await client.post(
        "/api/items/upload",
        files={"file": ("big.txt", b"way more than eight bytes", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 413


async def test_upload_resolves_type_from_content_type_and_markdown_ext(
    client, auth_headers
) -> None:
    # No filename extension -> resolved via content-type.
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"), patch(
        "app.core.document_extract._extract_pdf_text", return_value="body from ct-detected pdf"
    ):
        ct_resp = await client.post(
            "/api/items/upload",
            files={"file": ("document", b"%PDF-1.4 bytes", "application/pdf")},
            headers=auth_headers,
        )
    assert ct_resp.status_code == 201, ct_resp.text
    assert ct_resp.json()["kind"] == "pdf"

    # `.markdown` extension maps to md.
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        md_resp = await client.post(
            "/api/items/upload",
            files={"file": ("readme.markdown", b"# Hi\n\nbody text", "text/markdown")},
            headers=auth_headers,
        )
    assert md_resp.status_code == 201, md_resp.text
    assert md_resp.json()["kind"] == "note"


async def test_upload_same_document_is_idempotent(client, auth_headers) -> None:
    content = b"# Dup\n\nexactly the same content here"
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        first = await client.post(
            "/api/items/upload",
            files={"file": ("dup.md", content, "text/markdown")},
            headers=auth_headers,
        )
        second = await client.post(
            "/api/items/upload",
            files={"file": ("dup.md", content, "text/markdown")},
            headers=auth_headers,
        )
    assert first.status_code == 201 and second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]


# --- POST /items/{id}/reprocess (needs_input / failed recovery) ---


async def test_reprocess_with_pasted_body(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "url", "kind": "article", "url": "https://x/failed"},
            headers=auth_headers,
        )
    iid = created.json()["id"]
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay"
    ) as delay:
        r = await client.post(
            f"/api/items/{iid}/reprocess",
            json={"body": "Pasted article text the fetch missed."},
            headers=auth_headers,
        )
    assert r.status_code == 200, r.text
    delay.assert_called_once()
    got = await client.get(f"/api/items/{iid}", headers=auth_headers)
    assert got.json()["body"] == "Pasted article text the fetch missed."


async def test_reprocess_no_body_retries_the_source(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "url", "kind": "article", "url": "https://x/y"},
            headers=auth_headers,
        )
    iid = created.json()["id"]
    with patch(
        "app.tasks.item_summary_generation.generate_item_summary_task.delay"
    ) as delay:
        r = await client.post(f"/api/items/{iid}/reprocess", json={}, headers=auth_headers)
    assert r.status_code == 200, r.text
    delay.assert_called_once()  # re-enqueued to retry the fetch


async def test_reprocess_unknown_item_404(client, auth_headers) -> None:
    from uuid import uuid4

    r = await client.post(
        f"/api/items/{uuid4()}/reprocess", json={"body": "x"}, headers=auth_headers
    )
    assert r.status_code == 404


async def test_reprocess_nothing_to_process_422(client, auth_headers, db_session) -> None:
    from uuid import UUID

    from sqlalchemy import select

    from app.models.item import Item

    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "temp"},
            headers=auth_headers,
        )
    iid = created.json()["id"]
    item = (
        await db_session.execute(select(Item).where(Item.id == UUID(iid)))
    ).scalar_one()
    item.body = ""
    item.url = None
    await db_session.flush()
    r = await client.post(f"/api/items/{iid}/reprocess", json={}, headers=auth_headers)
    assert r.status_code == 422


async def test_patch_item_moves_between_folders_and_clears(client, auth_headers) -> None:
    folder = await _create_folder(client, auth_headers, name="Research")
    created = await client.post(
        "/api/items",
        json={"source": "paste", "kind": "note", "body": "filed note"},
        headers=auth_headers,
    )
    item_id = created.json()["id"]
    assert created.json()["folder_id"] is None

    moved = await client.patch(
        f"/api/items/{item_id}", json={"folder_id": folder["id"]}, headers=auth_headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["folder_id"] == folder["id"]

    cleared = await client.patch(
        f"/api/items/{item_id}", json={"folder_id": None}, headers=auth_headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["folder_id"] is None

    # Empty body -> folder untouched (distinguishes "absent" from "null").
    moved_again = await client.patch(
        f"/api/items/{item_id}", json={"folder_id": folder["id"]}, headers=auth_headers
    )
    assert moved_again.json()["folder_id"] == folder["id"]
    untouched = await client.patch(f"/api/items/{item_id}", json={}, headers=auth_headers)
    assert untouched.status_code == 200
    assert untouched.json()["folder_id"] == folder["id"]


async def test_patch_item_rejects_foreign_folder_and_missing_item(client, auth_headers) -> None:
    created = await client.post(
        "/api/items",
        json={"source": "paste", "kind": "note", "body": "x"},
        headers=auth_headers,
    )
    item_id = created.json()["id"]

    other_headers = await _register_headers(client)
    foreign_folder = await _create_folder(client, other_headers, name="Foreign")
    resp = await client.patch(
        f"/api/items/{item_id}",
        json={"folder_id": foreign_folder["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 404

    missing = await client.patch(
        f"/api/items/{uuid4()}", json={"folder_id": None}, headers=auth_headers
    )
    assert missing.status_code == 404


# --- list filters, summary payload, delete 404 -------------------------------


async def _create_item_with_summary(client, db_session, headers: dict[str, str]) -> str:
    """Create an item via the API and attach a stored summary directly."""
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": f"summary body {uuid4().hex}"},
            headers=headers,
        )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    db_session.add(
        ItemSummary(
            item_id=UUID(item_id),
            summary="Item summary.",
            key_points=["Point"],
            action_items=[{"task": "Follow up"}],
            topics=["topic"],
            people_mentioned=["Alice"],
            highlights=[],
            key_moments=[{"moment": "Important moment", "why_it_matters": "It matters"}],
            sentiment="neutral",
        )
    )
    await db_session.flush()
    return item_id


async def test_get_item_returns_summary_payload(client, auth_headers, db_session) -> None:
    item_id = await _create_item_with_summary(client, db_session, auth_headers)

    detail = await client.get(f"/api/items/{item_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["status"] == "ready"
    assert data["summary"]["summary"] == "Item summary."
    assert data["summary"]["key_moments"][0]["moment"] == "Important moment"
    assert data["summary"]["people_mentioned"] == ["Alice"]

    listing = await client.get("/api/items", headers=auth_headers)
    entry = next(e for e in listing.json()["items"] if e["id"] == item_id)
    assert entry["has_summary"] is True
    assert entry["status"] == "ready"


async def test_list_items_filters_by_source(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "pasted body"},
            headers=auth_headers,
        )
        await client.post(
            "/api/items",
            json={"source": "telegram", "kind": "note", "body": "forwarded body"},
            headers=auth_headers,
        )
    pasted = await client.get("/api/items?source=paste", headers=auth_headers)
    assert pasted.status_code == 200
    data = pasted.json()
    assert data["total"] == 1
    assert data["items"][0]["source"] == "paste"


async def test_list_items_filters_by_folder(client, auth_headers) -> None:
    folder = await _create_folder(client, auth_headers, name="Filtered")
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        foldered = await client.post(
            "/api/items",
            json={
                "source": "paste",
                "kind": "note",
                "body": "in folder",
                "folder_id": folder["id"],
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "loose item"},
            headers=auth_headers,
        )
    listing = await client.get(f"/api/items?folder_id={folder['id']}", headers=auth_headers)
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == foldered.json()["id"]

    unknown = await client.get(f"/api/items?folder_id={uuid4()}", headers=auth_headers)
    assert unknown.status_code == 404


async def test_delete_unknown_item_404(client, auth_headers) -> None:
    resp = await client.delete(f"/api/items/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Item not found"


# --- summary audio: state, start, file --------------------------------------


async def test_enqueue_summary_audio_generation_sends_celery_task() -> None:
    artifact_id = uuid4()
    with patch("app.tasks.celery_app.celery_app.send_task") as send_task:
        send_task.return_value = SimpleNamespace(id="task-123")
        assert enqueue_summary_audio_generation(artifact_id) == "task-123"
    send_task.assert_called_once_with(
        "app.tasks.summary_audio_generation.generate_summary_audio",
        kwargs={"artifact_id": str(artifact_id)},
    )


async def test_get_item_summary_audio_requires_item_and_summary(client, auth_headers) -> None:
    missing = await client.get(f"/api/items/{uuid4()}/summary/audio", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Item not found"

    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "no summary yet"},
            headers=auth_headers,
        )
    unsummarized = await client.get(
        f"/api/items/{created.json()['id']}/summary/audio", headers=auth_headers
    )
    assert unsummarized.status_code == 404
    assert unsummarized.json()["detail"] == "Summary not generated"


async def test_get_item_summary_audio_reports_not_started(
    client, auth_headers, db_session
) -> None:
    item_id = await _create_item_with_summary(client, db_session, auth_headers)

    state = await client.get(f"/api/items/{item_id}/summary/audio", headers=auth_headers)

    assert state.status_code == 200, state.text
    payload = state.json()
    assert payload["source_kind"] == "item"
    assert payload["source_id"] == item_id
    assert payload["status"] == "not_started"
    assert payload["audio_url"] is None


async def test_start_item_summary_audio_translates_summary_audio_error(
    client, auth_headers
) -> None:
    # No such item -> SummaryAudioError(source_not_found) surfaces as its status code.
    resp = await client.post(f"/api/items/{uuid4()}/summary/audio", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found."


async def test_start_item_summary_audio_enqueue_failure_is_503(
    client, auth_headers, db_session, monkeypatch
) -> None:
    def _boom(_artifact_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr("app.api.routes.items.enqueue_summary_audio_generation", _boom)
    item_id = await _create_item_with_summary(client, db_session, auth_headers)

    resp = await client.post(f"/api/items/{item_id}/summary/audio", headers=auth_headers)

    assert resp.status_code == 503
    artifact = (
        await db_session.execute(
            select(SummaryAudioArtifact).where(SummaryAudioArtifact.item_id == UUID(item_id))
        )
    ).scalar_one()
    assert artifact.status == SummaryAudioStatus.FAILED.value
    assert artifact.error_code == "summary_audio_enqueue_failed"


async def test_get_item_summary_audio_file_requires_item_summary_and_artifact(
    client, auth_headers, db_session
) -> None:
    missing = await client.get(f"/api/items/{uuid4()}/summary/audio/file", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Item not found"

    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        created = await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "body": "file but no summary"},
            headers=auth_headers,
        )
    unsummarized = await client.get(
        f"/api/items/{created.json()['id']}/summary/audio/file", headers=auth_headers
    )
    assert unsummarized.status_code == 404
    assert unsummarized.json()["detail"] == "Summary not generated"

    item_id = await _create_item_with_summary(client, db_session, auth_headers)
    no_artifact = await client.get(
        f"/api/items/{item_id}/summary/audio/file", headers=auth_headers
    )
    assert no_artifact.status_code == 404
    assert no_artifact.json()["detail"] == "Summary audio has not been created."


async def test_item_summary_audio_state_and_file_round_trip(
    client, auth_headers, db_session, monkeypatch, tmp_path
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "summary_audio_storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.api.routes.items.enqueue_summary_audio_generation",
        lambda artifact_id: "task-summary-audio",
    )
    item_id = await _create_item_with_summary(client, db_session, auth_headers)

    queued = await client.post(f"/api/items/{item_id}/summary/audio", headers=auth_headers)
    assert queued.status_code == 202, queued.text

    artifact = (
        await db_session.execute(
            select(SummaryAudioArtifact).where(SummaryAudioArtifact.item_id == UUID(item_id))
        )
    ).scalar_one()
    audio_path = tmp_path / str(artifact.user_id) / f"{artifact.id}.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"ID3item-summary-audio")
    artifact.status = SummaryAudioStatus.SUCCEEDED.value
    artifact.stage = "complete"
    artifact.progress_percent = 100
    artifact.storage_path = f"{artifact.user_id}/{artifact.id}.mp3"
    artifact.content_type = "audio/mpeg"
    artifact.byte_size = audio_path.stat().st_size
    artifact.completed_at = datetime.now(timezone.utc)
    await db_session.flush()

    state = await client.get(f"/api/items/{item_id}/summary/audio", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["audio_url"] == f"/api/items/{item_id}/summary/audio/file"

    streamed = await client.get(
        f"/api/items/{item_id}/summary/audio/file",
        headers={**auth_headers, "Range": "bytes=0-2"},
    )
    assert streamed.status_code == 206
    assert streamed.headers["content-type"] == "audio/mpeg"
    assert streamed.content == b"ID3"
