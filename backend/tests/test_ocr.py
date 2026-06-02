"""Scanned-PDF OCR via the vision LLM — text on success, "" for a no-text doc,
OcrError on an API failure, and the correct Responses-API input_file request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import ocr
from app.core.ocr import OcrError, ocr_pdf

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
