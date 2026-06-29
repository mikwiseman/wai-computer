"""Document extraction and upload-format routing."""

from __future__ import annotations

import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.core import document_extract as document_extract_module
from app.core.document_extract import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
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


def _docx_xml_bytes(document_xml: str) -> bytes:
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


def _odf_bytes(mime_type: str, body_xml: str) -> bytes:
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <office:document-content
        xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
        xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
        xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
        xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">
      <office:body>{body_xml}</office:body>
    </office:document-content>
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", mime_type)
        zf.writestr("content.xml", content_xml)
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


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected"),
    [
        ("legacy.xls", "application/vnd.ms-excel", "xls"),
        ("slides.ppt", "application/vnd.ms-powerpoint", "ppt"),
        ("brief.odt", "application/vnd.oasis.opendocument.text", "odt"),
        ("sheet.ods", "application/vnd.oasis.opendocument.spreadsheet", "ods"),
        ("deck.odp", "application/vnd.oasis.opendocument.presentation", "odp"),
        ("book.epub", "application/epub+zip", "epub"),
        ("mail.eml", "message/rfc822", "eml"),
        ("outlook.msg", "application/vnd.ms-outlook", "msg"),
        ("snapshot.mhtml", "application/x-mimearchive", "mhtml"),
        ("config.yaml", "application/x-yaml", "yaml"),
        ("config.yml", "text/yaml", "yaml"),
        ("feed.xml", "application/xml", "xml"),
    ],
)
def test_resolve_document_extension_covers_broad_document_formats(
    filename: str,
    mime_type: str,
    expected: str,
) -> None:
    assert resolve_document_extension(filename, None) == expected
    assert resolve_document_extension(None, mime_type) == expected
    assert expected in SUPPORTED_DOCUMENT_EXTENSIONS


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
async def test_extract_docx_handles_inline_breaks_tabs_and_text_fallback() -> None:
    rich_docx = _docx_xml_bytes(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>Alpha</w:t><w:tab/><w:t>Beta</w:t><w:br/><w:t>Gamma</w:t></w:r></w:p></w:body>
        </w:document>
        """
    )
    assert await extract_document_text("docx", rich_docx) == "Alpha Beta\nGamma"

    fallback_docx = _docx_xml_bytes(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:r><w:t>Loose text body</w:t></w:r></w:body>
        </w:document>
        """
    )
    assert await extract_document_text("docx", fallback_docx) == "Loose text body"


@pytest.mark.asyncio
async def test_extract_pdf_handles_text_ocr_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_extract_module, "_extract_pdf_text", lambda _data: " PDF body ")
    assert await extract_document_text("pdf", b"pdf") == "PDF body"

    monkeypatch.setattr(document_extract_module, "_extract_pdf_text", lambda _data: "")
    monkeypatch.setattr(
        document_extract_module,
        "get_settings",
        lambda: SimpleNamespace(ocr_enabled=False, ocr_max_pages=2),
    )
    with pytest.raises(DocumentExtractionError) as no_text:
        await extract_document_text("pdf", b"pdf")
    assert no_text.value.code == "pdf_no_text"

    monkeypatch.setattr(
        document_extract_module,
        "get_settings",
        lambda: SimpleNamespace(ocr_enabled=True, ocr_max_pages=2),
    )
    monkeypatch.setattr(document_extract_module, "_pdf_page_count", lambda _data: 3)
    with pytest.raises(DocumentExtractionError) as too_long:
        await extract_document_text("pdf", b"pdf")
    assert too_long.value.code == "pdf_ocr_too_long"

    ocr_module = ModuleType("app.core.ocr")

    class FakeOcrError(Exception):
        pass

    async def fake_ocr_pdf(_data: bytes, **_kwargs: object) -> str:
        return " OCR body "

    ocr_module.OcrError = FakeOcrError
    ocr_module.ocr_pdf = fake_ocr_pdf
    monkeypatch.setitem(sys.modules, "app.core.ocr", ocr_module)
    monkeypatch.setattr(document_extract_module, "_pdf_page_count", lambda _data: 1)

    assert await extract_document_text("pdf", b"pdf") == "OCR body"

    async def fail_ocr_pdf(_data: bytes, **_kwargs: object) -> str:
        raise FakeOcrError("ocr provider failed")

    ocr_module.ocr_pdf = fail_ocr_pdf
    with pytest.raises(DocumentExtractionError) as ocr_failed:
        await extract_document_text("pdf", b"pdf")
    assert ocr_failed.value.code == "ocr_failed"

    async def empty_ocr_pdf(_data: bytes, **_kwargs: object) -> str:
        return ""

    ocr_module.ocr_pdf = empty_ocr_pdf
    with pytest.raises(DocumentExtractionError) as empty_ocr:
        await extract_document_text("pdf", b"pdf")
    assert empty_ocr.value.code == "no_readable_text"


@pytest.mark.asyncio
async def test_extract_html_falls_back_and_surfaces_parser_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trafilatura_module = ModuleType("trafilatura")
    trafilatura_module.extract = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "trafilatura", trafilatura_module)

    html = (
        b"<html><body><script>hidden text</script><h1>Visible heading</h1>"
        b"<p>Readable paragraph body.</p></body></html>"
    )
    text = await extract_document_text("html", html)
    assert "Visible heading" in text
    assert "Readable paragraph body" in text
    assert "hidden text" not in text

    def fail_extract(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("parser failed")

    trafilatura_module.extract = fail_extract
    with pytest.raises(DocumentExtractionError) as exc:
        await extract_document_text("html", html)
    assert exc.value.code == "html_extract_failed"


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
@pytest.mark.parametrize(
    ("ext", "expected_mime"),
    [
        ("xls", "application/vnd.ms-excel"),
        ("ppt", "application/vnd.ms-powerpoint"),
        ("epub", "application/epub+zip"),
        ("eml", "message/rfc822"),
        ("msg", "application/vnd.ms-outlook"),
        ("mhtml", "application/x-mimearchive"),
        ("yaml", "application/x-yaml"),
        ("xml", "application/xml"),
    ],
)
async def test_extract_document_text_uses_kreuzberg_for_broad_formats(
    monkeypatch: pytest.MonkeyPatch,
    ext: str,
    expected_mime: str,
) -> None:
    calls: list[tuple[bytes, str]] = []

    def fake_extract_bytes_sync(data: bytes, mime_type: str):
        calls.append((data, mime_type))
        return SimpleNamespace(content=f"Readable {ext} body")

    monkeypatch.setattr(
        "app.core.document_extract.extract_bytes_sync",
        fake_extract_bytes_sync,
    )

    text = await extract_document_text(ext, b"document bytes")

    assert text == f"Readable {ext} body"
    assert calls == [(b"document bytes", expected_mime)]


@pytest.mark.asyncio
async def test_extract_document_text_handles_open_document_formats() -> None:
    odt_text = await extract_document_text(
        "odt",
        _odf_bytes(
            "application/vnd.oasis.opendocument.text",
            "<office:text><text:p>ODT roadmap body</text:p></office:text>",
        ),
    )
    assert "ODT roadmap body" in odt_text

    ods_text = await extract_document_text(
        "ods",
        _odf_bytes(
            "application/vnd.oasis.opendocument.spreadsheet",
            (
                "<office:spreadsheet><table:table><table:table-row>"
                "<table:table-cell><text:p>ODS metric</text:p></table:table-cell>"
                "</table:table-row></table:table></office:spreadsheet>"
            ),
        ),
    )
    assert "ODS metric" in ods_text

    odp_text = await extract_document_text(
        "odp",
        _odf_bytes(
            "application/vnd.oasis.opendocument.presentation",
            (
                "<office:presentation><draw:page><text:p>ODP slide body</text:p>"
                "</draw:page></office:presentation>"
            ),
        ),
    )
    assert "ODP slide body" in odp_text


@pytest.mark.asyncio
async def test_extract_document_text_surfaces_malformed_office_documents() -> None:
    missing_docx = BytesIO()
    with zipfile.ZipFile(missing_docx, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
    with pytest.raises(DocumentExtractionError) as missing_docx_error:
        await extract_document_text("docx", missing_docx.getvalue())
    assert missing_docx_error.value.code == "docx_extract_failed"

    broken_docx = BytesIO()
    with zipfile.ZipFile(broken_docx, "w") as zf:
        zf.writestr("word/document.xml", b"<not xml")
    with pytest.raises(DocumentExtractionError) as broken_docx_error:
        await extract_document_text("docx", broken_docx.getvalue())
    assert broken_docx_error.value.code == "xml_parse_failed"

    empty_pptx = BytesIO()
    with zipfile.ZipFile(empty_pptx, "w") as zf:
        zf.writestr("[Content_Types].xml", "")
    with pytest.raises(DocumentExtractionError) as empty_pptx_error:
        await extract_document_text("pptx", empty_pptx.getvalue())
    assert empty_pptx_error.value.code == "no_readable_text"

    missing_odf = BytesIO()
    with zipfile.ZipFile(missing_odf, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    with pytest.raises(DocumentExtractionError) as missing_odf_error:
        await extract_document_text("odt", missing_odf.getvalue())
    assert missing_odf_error.value.code == "opendocument_extract_failed"

    broken_odf = BytesIO()
    with zipfile.ZipFile(broken_odf, "w") as zf:
        zf.writestr("content.xml", b"<not xml")
    with pytest.raises(DocumentExtractionError) as broken_odf_error:
        await extract_document_text("odt", broken_odf.getvalue())
    assert broken_odf_error.value.code == "xml_parse_failed"


@pytest.mark.asyncio
async def test_extract_xlsx_handles_numeric_and_missing_shared_strings() -> None:
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row><c><v>42</v></c><c t="inlineStr"><is><t>units</t></is></c></row>
      </sheetData>
    </worksheet>
    """
    workbook = BytesIO()
    with zipfile.ZipFile(workbook, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)

    text = await extract_document_text("xlsx", workbook.getvalue())

    assert text == "42, units"


@pytest.mark.asyncio
async def test_extract_with_kreuzberg_surfaces_converter_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_dependency(_data: bytes, _mime_type: str) -> object:
        raise document_extract_module.MissingDependencyError("missing converter")

    monkeypatch.setattr(
        document_extract_module,
        "extract_bytes_sync",
        missing_dependency,
    )
    with pytest.raises(DocumentExtractionError) as missing:
        await extract_document_text("xls", b"legacy spreadsheet")
    assert missing.value.code == "converter_missing"

    def extraction_failure(_data: bytes, _mime_type: str) -> object:
        raise document_extract_module.KreuzbergError("conversion failed")

    monkeypatch.setattr(
        document_extract_module,
        "extract_bytes_sync",
        extraction_failure,
    )
    with pytest.raises(DocumentExtractionError) as failed:
        await extract_document_text("xls", b"legacy spreadsheet")
    assert failed.value.code == "document_extract_failed"

    monkeypatch.setattr(
        document_extract_module,
        "extract_bytes_sync",
        lambda _data, _mime_type: SimpleNamespace(content=None),
    )
    with pytest.raises(DocumentExtractionError) as non_string:
        await extract_document_text("xls", b"legacy spreadsheet")
    assert non_string.value.code == "document_extract_failed"

    monkeypatch.setattr(
        document_extract_module,
        "extract_bytes_sync",
        lambda _data, _mime_type: SimpleNamespace(content=""),
    )
    with pytest.raises(DocumentExtractionError) as empty:
        await extract_document_text("xls", b"legacy spreadsheet")
    assert empty.value.code == "no_readable_text"


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
    assert document_kind_for_extension("odt") == "document"
    assert document_kind_for_extension("xlsx") == "spreadsheet"
    assert document_kind_for_extension("xls") == "spreadsheet"
    assert document_kind_for_extension("pptx") == "presentation"
    assert document_kind_for_extension("odp") == "presentation"
    assert document_kind_for_extension("eml") == "email"
