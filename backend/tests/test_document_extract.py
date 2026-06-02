"""Document extraction and upload-format routing."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.core.document_extract import (
    DocumentExtractionError,
    document_kind_for_extension,
    extract_document_text,
    resolve_document_extension,
)
from app.core.item_titles import title_from_filename


def _docx_bytes(text: str) -> bytes:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
    </w:document>
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_resolve_document_extension_covers_common_materials() -> None:
    assert resolve_document_extension("contract.pdf", "application/octet-stream") == "pdf"
    assert resolve_document_extension("brief.DOCX", None) == "docx"
    assert resolve_document_extension("legacy.doc", "application/msword") == "doc"
    assert resolve_document_extension("report.html", None) == "html"
    assert resolve_document_extension(None, "text/csv") == "csv"
    assert resolve_document_extension("slides.pptx", None) == "pptx"
    assert resolve_document_extension("sheet.xlsx", None) == "xlsx"
    assert resolve_document_extension("archive.zip", "application/zip") == ""


def test_title_from_filename_removes_generic_placeholders() -> None:
    assert title_from_filename("VypZapEGRUL_b5ffaec9.pdf") == "VypZapEGRUL_b5ffaec9"
    assert title_from_filename("[Untitled].pdf") is None
    assert title_from_filename("untitled") is None


@pytest.mark.asyncio
async def test_extract_document_text_handles_html_docx_json_and_csv() -> None:
    html = (
        b"<html><head><title>STT Benchmarks</title></head>"
        b"<body><h1>Benchmarks</h1><p>Deepgram compared with Whisper.</p></body></html>"
    )
    assert "Deepgram compared with Whisper" in await extract_document_text("html", html)

    assert "Agreement text" in await extract_document_text("docx", _docx_bytes("Agreement text"))

    json_text = await extract_document_text("json", json.dumps({"plan": "launch"}).encode())
    assert '"plan": "launch"' in json_text

    csv_text = await extract_document_text("csv", b"name,value\nlatency,120\n")
    assert "name, value" in csv_text
    assert "latency, 120" in csv_text


@pytest.mark.asyncio
async def test_extract_legacy_doc_requires_converter(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.core.document_extract.shutil.which", lambda name: None)
    with pytest.raises(DocumentExtractionError) as exc:
        await extract_document_text("doc", b"binary doc")
    assert exc.value.code == "converter_missing"


def test_document_kind_for_extension() -> None:
    assert document_kind_for_extension("pdf") == "pdf"
    assert document_kind_for_extension("html") == "article"
    assert document_kind_for_extension("docx") == "document"
    assert document_kind_for_extension("xlsx") == "spreadsheet"
    assert document_kind_for_extension("pptx") == "presentation"
