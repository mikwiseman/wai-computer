"""OCR for scanned/image PDFs via the configured vision LLM (gpt-5.5).

When pdfplumber finds no text layer, the PDF is sent straight to the model via
the Responses API ``input_file`` — gpt-5.5 reads the document natively, so there
is NO rasterizer / Tesseract / docling dependency. No fallback: an API failure
surfaces as :class:`OcrError`; a document that genuinely has no text returns "".

Privacy: the PDF bytes go only to OpenAI (same trust boundary as summaries); we
never log the document or its text.
"""

from __future__ import annotations

import base64
import logging
import time
from uuid import UUID

from app.config import get_settings
from app.core.ai_usage import (
    FEATURE_OCR,
    OPENAI_PROVIDER,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    record_ai_usage_event_standalone,
)
from app.core.openai_client import get_openai_client
from app.core.openai_responses import (
    OpenAIResponseError,
    ensure_response_completed,
    response_output_text,
)

logger = logging.getLogger(__name__)

_OCR_INSTRUCTION = (
    "Transcribe ALL text from this document verbatim, preserving reading order. "
    "Include every heading, paragraph, list item, and table cell. Do NOT "
    "summarise, translate, or add commentary — output only the document's text."
)


class OcrError(Exception):
    """Raised when OCR of a scanned PDF fails (API error / refusal / incomplete)."""


async def ocr_pdf(
    data: bytes,
    *,
    model: str | None = None,
    usage_user_id: UUID | str | None = None,
    usage_item_id: UUID | str | None = None,
) -> str:
    """OCR a (scanned) PDF via the vision LLM.

    Returns the extracted text (``""`` if the document genuinely has none).
    Raises :class:`OcrError` on an API failure / refusal — never a silent empty.
    """
    if not data:
        return ""
    settings = get_settings()
    client = get_openai_client()
    encoded = base64.b64encode(data).decode("ascii")
    started = time.perf_counter()
    response = None
    resolved_model = model or settings.openai_llm_model
    try:
        response = await client.responses.create(
            model=resolved_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _OCR_INSTRUCTION},
                        {
                            "type": "input_file",
                            "filename": "document.pdf",
                            "file_data": f"data:application/pdf;base64,{encoded}",
                        },
                    ],
                }
            ],
        )
        ensure_response_completed(response, operation="PDF OCR")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a typed OcrError
        await record_ai_usage_event_standalone(
            provider=OPENAI_PROVIDER,
            feature=FEATURE_OCR,
            operation="ocr.pdf",
            status=STATUS_FAILED,
            user_id=usage_user_id,
            item_id=usage_item_id,
            model=resolved_model,
            response=response,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        logger.warning("pdf OCR failed error_type=%s", type(exc).__name__)
        raise OcrError(f"OCR request failed: {type(exc).__name__}") from exc

    try:
        text = response_output_text(response)
        await record_ai_usage_event_standalone(
            provider=OPENAI_PROVIDER,
            feature=FEATURE_OCR,
            operation="ocr.pdf",
            status=STATUS_SUCCEEDED,
            user_id=usage_user_id,
            item_id=usage_item_id,
            model=resolved_model,
            response=response,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return text
    except OpenAIResponseError:
        await record_ai_usage_event_standalone(
            provider=OPENAI_PROVIDER,
            feature=FEATURE_OCR,
            operation="ocr.pdf",
            status=STATUS_SUCCEEDED,
            user_id=usage_user_id,
            item_id=usage_item_id,
            model=resolved_model,
            response=response,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        # The model returned no text — the document genuinely has none (not an
        # error). The caller treats an empty body as "no readable text".
        return ""
