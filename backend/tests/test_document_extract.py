"""Document extraction and upload-format routing."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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


def _pptx_bytes(text: str) -> bytes:
    slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
           xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
        zf.writestr("ppt/slides/slide1.xml", slide_xml)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <si><t>Metric</t></si><si><t>Latency</t></si>
    </sst>
    """
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row>
          <c t="s"><v>0</v></c>
          <c t="s"><v>1</v></c>
          <c><v>120</v></c>
          <c t="inlineStr"><is><t>ms</t></is></c>
        </row>
      </sheetData>
    </worksheet>
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
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
    assert resolve_document_extension("note.markdown", None) == "md"
    assert resolve_document_extension("page.htm", None) == "html"


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
async def test_extract_document_text_handles_pptx_xlsx_rtf_and_text_encodings() -> None:
    pptx_text = await extract_document_text("pptx", _pptx_bytes("Launch slide body"))
    assert "Launch slide body" in pptx_text

    xlsx_text = await extract_document_text("xlsx", _xlsx_bytes())
    assert "Metric, Latency, 120, ms" in xlsx_text

    rtf_text = await extract_document_text(
        "rtf", br"{\rtf1\ansi Launch\par review\line caf\'e9}"
    )
    assert "Launch" in rtf_text
    assert "review" in rtf_text

    utf16_text = await extract_document_text("txt", "Launch memo body".encode("utf-16"))
    assert utf16_text == "Launch memo body"

    cp1251_text = await extract_document_text("txt", "Русский текст".encode("cp1251"))
    assert cp1251_text == "Русский текст"


@pytest.mark.asyncio
async def test_extract_document_text_rejects_invalid_or_empty_documents() -> None:
    with pytest.raises(DocumentExtractionError) as unsupported:
        await extract_document_text("zip", b"PK")
    assert unsupported.value.code == "unsupported_file_type"

    with pytest.raises(DocumentExtractionError) as docx_error:
        await extract_document_text("docx", b"not a zip")
    assert docx_error.value.code == "docx_extract_failed"

    with pytest.raises(DocumentExtractionError) as pptx_error:
        await extract_document_text("pptx", b"not a zip")
    assert pptx_error.value.code == "pptx_extract_failed"

    with pytest.raises(DocumentExtractionError) as xlsx_error:
        await extract_document_text("xlsx", b"not a zip")
    assert xlsx_error.value.code == "xlsx_extract_failed"

    with pytest.raises(DocumentExtractionError) as json_error:
        await extract_document_text("json", b"{bad json")
    assert json_error.value.code == "json_parse_failed"

    with pytest.raises(DocumentExtractionError) as text_error:
        await extract_document_text("txt", b"\x00\x01\x02\x03")
    assert text_error.value.code == "text_decode_failed"


@pytest.mark.asyncio
async def test_extract_legacy_doc_requires_converter(monkeypatch, tmp_path: Path) -> None:
    del tmp_path
    monkeypatch.setattr("app.core.document_extract.shutil.which", lambda name: None)
    with pytest.raises(DocumentExtractionError) as exc:
        await extract_document_text("doc", b"binary doc")
    assert exc.value.code == "converter_missing"


@pytest.mark.asyncio
async def test_extract_legacy_doc_uses_converter_and_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.document_extract.shutil.which", lambda name: "/bin/antiword")
    monkeypatch.setattr(
        "app.core.document_extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="Legacy doc body"),
    )
    assert await extract_document_text("doc", b"binary doc") == "Legacy doc body"

    monkeypatch.setattr(
        "app.core.document_extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(DocumentExtractionError) as exc:
        await extract_document_text("doc", b"binary doc")
    assert exc.value.code == "doc_extract_failed"


def test_document_kind_for_extension() -> None:
    assert document_kind_for_extension("pdf") == "pdf"
    assert document_kind_for_extension("html") == "article"
    assert document_kind_for_extension("docx") == "document"
    assert document_kind_for_extension("xlsx") == "spreadsheet"
    assert document_kind_for_extension("pptx") == "presentation"
