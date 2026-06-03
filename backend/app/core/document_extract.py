"""Readable document extraction for Materials ingestion.

The upload surface is intentionally broader than the audio transcription path:
documents become Items, media becomes Recordings, and unsupported binary files
return an explicit user-facing error instead of being silently ignored.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from html import unescape
from html.parser import HTMLParser
from typing import Any, Iterable
from unicodedata import category
from xml.etree import ElementTree

from app.config import get_settings
from app.core.source_fetch import SourceFetchError, _extract_pdf_text, _pdf_page_count

SUPPORTED_DOCUMENT_EXTENSIONS = {
    "pdf",
    "txt",
    "md",
    "html",
    "docx",
    "doc",
    "rtf",
    "csv",
    "json",
    "pptx",
    "xlsx",
}

_EXT_ALIASES = {
    "markdown": "md",
    "htm": "html",
}

_MIME_EXTENSIONS = {
    "application/pdf": "pdf",
    "text/markdown": "md",
    "text/x-markdown": "md",
    "text/plain": "txt",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/msword": "doc",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "text/csv": "csv",
    "application/csv": "csv",
    "application/json": "json",
    "text/json": "json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


class DocumentExtractionError(Exception):
    """A document could not be converted into summarizable text."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_document_extension(filename: str | None, content_type: str | None) -> str:
    """Resolve a supported document extension from a filename or MIME type."""
    name = (filename or "").lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in name:
        suffix = name.rsplit(".", 1)[1]
        ext = _EXT_ALIASES.get(suffix, suffix)
        if ext in SUPPORTED_DOCUMENT_EXTENSIONS:
            return ext
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return _MIME_EXTENSIONS.get(ct, "")


def document_kind_for_extension(ext: str) -> str:
    """Map file formats onto the existing Item kind vocabulary."""
    if ext == "pdf":
        return "pdf"
    if ext == "html":
        return "article"
    if ext in {"pptx"}:
        return "presentation"
    if ext in {"xlsx", "csv"}:
        return "spreadsheet"
    if ext in {"doc", "docx", "rtf"}:
        return "document"
    return "note"


async def extract_document_text(
    ext: str,
    data: bytes,
    *,
    usage_user_id: Any | None = None,
) -> str:
    """Extract text for a supported document extension."""
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise DocumentExtractionError(
            "unsupported_file_type",
            "This file type is not supported yet.",
        )

    if ext == "pdf":
        return await _extract_pdf(data, usage_user_id=usage_user_id)
    if ext in {"txt", "md"}:
        return _decode_text(data)
    if ext == "html":
        return _extract_html(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext == "doc":
        return await asyncio.to_thread(_extract_doc_with_antiword, data)
    if ext == "rtf":
        return _extract_rtf(data)
    if ext == "csv":
        return _extract_csv(data)
    if ext == "json":
        return _extract_json(data)
    if ext == "pptx":
        return _extract_pptx(data)
    if ext == "xlsx":
        return _extract_xlsx(data)
    raise AssertionError(f"unhandled document extension: {ext}")


async def _extract_pdf(data: bytes, *, usage_user_id: Any | None = None) -> str:
    try:
        body = _extract_pdf_text(data)
    except SourceFetchError as exc:
        raise DocumentExtractionError(exc.code, exc.message) from exc
    if body.strip():
        return body.strip()

    settings = get_settings()
    if not settings.ocr_enabled:
        raise DocumentExtractionError(
            "pdf_no_text",
            "No readable text found in this PDF.",
        )

    from app.core.ocr import OcrError, ocr_pdf

    max_pages = settings.ocr_max_pages
    pages = _pdf_page_count(data)
    if pages > max_pages:
        raise DocumentExtractionError(
            "pdf_ocr_too_long",
            f"This scanned PDF is too long to OCR ({pages} pages; max {max_pages}).",
        )
    try:
        text = await ocr_pdf(data, usage_user_id=usage_user_id)
    except OcrError as exc:
        raise DocumentExtractionError("ocr_failed", str(exc)) from exc
    return _require_text(text, "No readable text found in this PDF.")


def _decode_text(data: bytes) -> str:
    encodings = ["utf-8-sig", "cp1251"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(1, "utf-16")
    for encoding in encodings:
        try:
            text = data.decode(encoding).strip()
        except UnicodeError:
            continue
        if _looks_like_readable_text(text):
            return text
    raise DocumentExtractionError(
        "text_decode_failed",
        "Couldn't read this text file. Save it as UTF-8 and try again.",
    )


def _looks_like_readable_text(text: str) -> bool:
    normalized = _normalize_extracted_text(text)
    if len(normalized) < 8:
        return False
    controls = sum(
        1
        for char in normalized
        if category(char).startswith("C") and char not in {"\n", "\r", "\t"}
    )
    return controls / max(len(normalized), 1) <= 0.02


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"br", "p", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return _normalize_extracted_text(" ".join(self._parts))


def _extract_html(data: bytes) -> str:
    html = _decode_text(data)
    extracted = None
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            output_format="markdown",
        )
    except ModuleNotFoundError:
        extracted = None
    except Exception as exc:
        raise DocumentExtractionError(
            "html_extract_failed",
            "Couldn't read this HTML file.",
        ) from exc
    if extracted and extracted.strip():
        return extracted.strip()

    parser = _HTMLTextParser()
    parser.feed(html)
    return _require_text(parser.text(), "No readable text found in this HTML file.")


def _extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DocumentExtractionError(
            "docx_extract_failed",
            "Couldn't read this DOCX file.",
        ) from exc
    text = _paragraph_text_from_xml(xml, paragraph_tag="p", text_tag="t")
    return _require_text(text, "No readable text found in this DOCX file.")


def _extract_pptx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            slide_names = sorted(
                name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)
            )
            slides = [
                _paragraph_text_from_xml(zf.read(name), paragraph_tag="p", text_tag="t")
                for name in slide_names
            ]
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError(
            "pptx_extract_failed",
            "Couldn't read this PPTX file.",
        ) from exc
    return _require_text(
        "\n\n".join(s for s in slides if s),
        "No readable text found in this PPTX file.",
    )


def _extract_xlsx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            shared_strings = _xlsx_shared_strings(zf)
            sheet_names = sorted(
                name for name in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
            )
            rows: list[str] = []
            for name in sheet_names:
                rows.extend(_xlsx_sheet_rows(zf.read(name), shared_strings))
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError(
            "xlsx_extract_failed",
            "Couldn't read this XLSX file.",
        ) from exc
    return _require_text("\n".join(rows), "No readable text found in this XLSX file.")


def _extract_doc_with_antiword(data: bytes) -> str:
    antiword = shutil.which("antiword")
    if not antiword:
        raise DocumentExtractionError(
            "converter_missing",
            "DOC import needs the document converter on the server.",
        )
    with tempfile.NamedTemporaryFile(suffix=".doc") as tmp:
        tmp.write(data)
        tmp.flush()
        result = subprocess.run(
            [antiword, tmp.name],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        raise DocumentExtractionError("doc_extract_failed", "Couldn't read this DOC file.")
    return _require_text(result.stdout, "No readable text found in this DOC file.")


def _extract_rtf(data: bytes) -> str:
    raw = _decode_text(data)

    def hex_repl(match: re.Match[str]) -> str:
        try:
            return bytes.fromhex(match.group(1)).decode("latin-1")
        except UnicodeError:
            return " "

    text = re.sub(r"\\'([0-9a-fA-F]{2})", hex_repl, raw)
    text = re.sub(r"\\(par|line)\b", "\n", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    text = text.replace("{", " ").replace("}", " ")
    return _require_text(
        _normalize_extracted_text(unescape(text)),
        "No readable text found in this RTF file.",
    )


def _extract_csv(data: bytes) -> str:
    text = _decode_text(data)
    reader = csv.reader(io.StringIO(text))
    lines = [", ".join(cell.strip() for cell in row if cell.strip()) for row in reader]
    return _require_text(
        "\n".join(line for line in lines if line),
        "No readable text found in this CSV file.",
    )


def _extract_json(data: bytes) -> str:
    text = _decode_text(data)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocumentExtractionError("json_parse_failed", "This JSON file is invalid.") from exc
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _paragraph_text_from_xml(xml: bytes, *, paragraph_tag: str, text_tag: str) -> str:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentExtractionError(
            "xml_parse_failed",
            "Couldn't parse this Office document.",
        ) from exc
    lines: list[str] = []
    for para in _iter_local(root, paragraph_tag):
        parts: list[str] = []
        for node in para.iter():
            local = _local_name(node.tag)
            if local == text_tag and node.text:
                parts.append(node.text)
            elif local == "tab":
                parts.append("\t")
            elif local in {"br", "cr"}:
                parts.append("\n")
        line = _normalize_extracted_text("".join(parts))
        if line:
            lines.append(line)
    if not lines:
        texts = [node.text for node in _iter_local(root, text_tag) if node.text]
        return _normalize_extracted_text(" ".join(texts))
    return "\n".join(lines)


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        xml = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(xml)
    values: list[str] = []
    for si in _iter_local(root, "si"):
        values.append(
            _normalize_extracted_text(
                " ".join(t.text or "" for t in _iter_local(si, "t"))
            )
        )
    return values


def _xlsx_sheet_rows(xml: bytes, shared_strings: list[str]) -> list[str]:
    root = ElementTree.fromstring(xml)
    rows: list[str] = []
    for row in _iter_local(root, "row"):
        cells: list[str] = []
        for cell in _iter_local(row, "c"):
            cell_type = cell.attrib.get("t")
            value = next(_iter_local(cell, "v"), None)
            if cell_type == "s" and value is not None and value.text:
                idx = int(value.text)
                cells.append(shared_strings[idx] if idx < len(shared_strings) else "")
            elif cell_type == "inlineStr":
                cells.append(" ".join(t.text or "" for t in _iter_local(cell, "t")))
            elif value is not None and value.text:
                cells.append(value.text)
        line = ", ".join(_normalize_extracted_text(cell) for cell in cells if cell.strip())
        if line:
            rows.append(line)
    return rows


def _iter_local(root: ElementTree.Element, local_name: str) -> Iterable[ElementTree.Element]:
    for node in root.iter():
        if _local_name(node.tag) == local_name:
            yield node


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_extracted_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _require_text(text: str, message: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        raise DocumentExtractionError("no_readable_text", message)
    return stripped
