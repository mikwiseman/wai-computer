"""API tests for the universal /items routes (Phase 1).

Background summarization is disabled in these tests by stubbing the Celery
task's ``.delay`` (the route imports it lazily), so we assert the synchronous
capture + feed + detail behaviour without a broker or OpenAI.
"""

from unittest.mock import patch

import pytest

from app.api.routes.items import _derive_status, _item_error
from app.models.item import Item

pytestmark = pytest.mark.asyncio


async def test_create_item_requires_body_or_url(client, auth_headers) -> None:
    resp = await client.post("/api/items", json={"source": "paste"}, headers=auth_headers)
    assert resp.status_code == 400


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


async def test_upload_markdown_creates_note_item(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
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


async def test_upload_pdf_extracts_text(client, auth_headers) -> None:
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"), patch(
        "app.core.source_fetch._extract_pdf_text",
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
        "app.core.source_fetch._extract_pdf_text",
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
        "app.core.source_fetch._extract_pdf_text", return_value=""
    ), patch("app.core.source_fetch._pdf_page_count", return_value=2), patch(
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
    with patch("app.core.source_fetch._extract_pdf_text", return_value=""), patch(
        "app.core.source_fetch._pdf_page_count", return_value=999
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

    with patch("app.core.source_fetch._extract_pdf_text", return_value=""), patch(
        "app.core.source_fetch._pdf_page_count", return_value=1
    ), patch("app.core.ocr.ocr_pdf", new=AsyncMock(return_value="")):
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("blank.pdf", b"%PDF-1.4 scanned", "application/pdf")},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "no readable text" in resp.json()["detail"].lower()


async def test_upload_video_enqueues_recording(client, auth_headers) -> None:
    # Video is no longer rejected — it's staged and handed to the recording pipeline.
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42 body", "video/mp4")},
            headers=auth_headers,
        )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"kind": "recording", "status": "processing"}
    delay.assert_called_once()
    kwargs = delay.call_args.kwargs
    assert kwargs["filename"] == "clip.mp4"
    assert kwargs["content_type"] == "video/mp4"
    assert kwargs["staged_path"].endswith(".mp4")


async def test_upload_audio_enqueues_recording(client, auth_headers) -> None:
    with patch("app.tasks.media_import.import_uploaded_media_task.delay") as delay:
        resp = await client.post(
            "/api/items/upload",
            files={"file": ("memo.mp3", b"ID3\x03\x00\x00\x00 audio bytes", "audio/mpeg")},
            headers=auth_headers,
        )
    assert resp.status_code == 202, resp.text
    delay.assert_called_once()
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
        "app.core.source_fetch._extract_pdf_text", return_value="body from ct-detected pdf"
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
