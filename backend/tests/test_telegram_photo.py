"""Unit tests for Telegram photo / image-document extraction."""

from app.api.routes.telegram import _extract_photo


def test_extract_photo_picks_largest_size():
    msg = {
        "photo": [
            {"file_id": "small", "file_unique_id": "us", "width": 90, "height": 60},
            {"file_id": "big", "file_unique_id": "ub", "width": 1280, "height": 720},
        ]
    }
    photo = _extract_photo(msg)
    assert photo is not None
    assert photo["kind"] == "photo"
    assert photo["file_id"] == "big"
    assert photo["mime_type"] == "image/jpeg"


def test_extract_photo_image_document_by_mime():
    msg = {"document": {"file_id": "f1", "file_unique_id": "u1", "mime_type": "image/png"}}
    photo = _extract_photo(msg)
    assert photo is not None
    assert photo["kind"] == "photo_document"
    assert photo["mime_type"] == "image/png"


def test_extract_photo_image_document_by_extension():
    msg = {"document": {"file_id": "f2", "file_unique_id": "u2", "file_name": "scan.PNG"}}
    photo = _extract_photo(msg)
    assert photo is not None
    assert photo["kind"] == "photo_document"


def test_extract_photo_ignores_non_image_document():
    msg = {"document": {"file_id": "f3", "file_name": "report.pdf", "mime_type": "application/pdf"}}
    assert _extract_photo(msg) is None


def test_extract_photo_ignores_voice_and_empty():
    assert _extract_photo({"voice": {"file_id": "v"}}) is None
    assert _extract_photo({}) is None
    assert _extract_photo({"photo": []}) is None
