"""Scanned-PDF OCR via the vision LLM — text on success, "" for a no-text doc,
OcrError on an API failure, and the correct Responses-API input_file request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import ocr
from app.core.ocr import OcrError, answer_about_images, ocr_images, ocr_pdf

pytestmark = pytest.mark.asyncio


def _fake_client(*, output_text: str = "", raises: Exception | None = None):
    if raises is not None:
        responses = SimpleNamespace(create=AsyncMock(side_effect=raises))
    else:
        resp = SimpleNamespace(
            output_text=output_text, status="completed", error=None, output=[]
        )
        responses = SimpleNamespace(create=AsyncMock(return_value=resp))
    return SimpleNamespace(responses=responses)


async def test_ocr_pdf_returns_transcribed_text() -> None:
    with patch.object(
        ocr, "get_openai_client",
        return_value=_fake_client(output_text="Scanned heading\n\nBody text."),
    ):
        assert await ocr_pdf(b"%PDF-1.4 scanned") == "Scanned heading\n\nBody text."


async def test_ocr_pdf_empty_document_returns_empty() -> None:
    # Model completed but returned only whitespace -> "" (not an error).
    with patch.object(ocr, "get_openai_client", return_value=_fake_client(output_text="   ")):
        assert await ocr_pdf(b"%PDF-1.4") == ""


async def test_ocr_pdf_api_failure_raises_ocrerror() -> None:
    with patch.object(
        ocr, "get_openai_client", return_value=_fake_client(raises=RuntimeError("boom"))
    ):
        with pytest.raises(OcrError):
            await ocr_pdf(b"%PDF-1.4")


async def test_ocr_pdf_empty_input_returns_empty() -> None:
    assert await ocr_pdf(b"") == ""


async def test_ocr_pdf_sends_pdf_as_input_file() -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_text="ok", status="completed", error=None, output=[])

    client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    with patch.object(ocr, "get_openai_client", return_value=client):
        await ocr_pdf(b"PDFDATA")
    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_file"
    assert content[1]["file_data"].startswith("data:application/pdf;base64,")


# --- answer_about_images (photo caption Q&A) ---


async def test_answer_about_images_sends_question_and_every_image() -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text="На чеке 1200 ₽.", status="completed", error=None, output=[]
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    with patch.object(ocr, "get_openai_client", return_value=client):
        answer = await answer_about_images(
            [(b"img-one", "image/png"), (b"img-two", "image/jpeg")],
            question="сколько тут итого?",
        )
    assert answer == "На чеке 1200 ₽."
    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "сколько тут итого?" in content[0]["text"]
    assert "2 image(s)" in content[0]["text"]
    assert [part["type"] for part in content[1:]] == ["input_image", "input_image"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"].startswith("data:image/jpeg;base64,")


async def test_answer_about_images_api_failure_raises_ocrerror() -> None:
    with patch.object(
        ocr, "get_openai_client", return_value=_fake_client(raises=RuntimeError("boom"))
    ):
        with pytest.raises(OcrError):
            await answer_about_images([(b"img", "image/jpeg")], question="что это?")


async def test_answer_about_images_empty_answer_raises_ocrerror() -> None:
    # An empty answer is a failure for Q&A (unlike OCR, where no text is valid).
    with patch.object(ocr, "get_openai_client", return_value=_fake_client(output_text="  ")):
        with pytest.raises(OcrError):
            await answer_about_images([(b"img", "image/jpeg")], question="что это?")


async def test_answer_about_images_requires_images_and_question() -> None:
    with pytest.raises(OcrError):
        await answer_about_images([], question="что это?")
    with pytest.raises(OcrError):
        await answer_about_images([(b"img", "image/jpeg")], question="   ")


# --- ocr_images (album OCR in one pass) ---


async def test_ocr_images_sends_all_images_with_album_instruction() -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text="Image 1: чек\nText: 1200", status="completed", error=None, output=[]
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    with patch.object(ocr, "get_openai_client", return_value=client):
        text = await ocr_images([(b"a", "image/png"), (b"b", "image/jpeg")])
    assert "Image 1: чек" in text
    content = captured["input"][0]["content"]
    assert "2 images" in content[0]["text"]
    assert [part["type"] for part in content[1:]] == ["input_image", "input_image"]


async def test_ocr_images_empty_input_returns_empty() -> None:
    assert await ocr_images([]) == ""


async def test_ocr_images_api_failure_raises_ocrerror() -> None:
    with patch.object(
        ocr, "get_openai_client", return_value=_fake_client(raises=RuntimeError("boom"))
    ):
        with pytest.raises(OcrError):
            await ocr_images([(b"img", "image/jpeg")])
