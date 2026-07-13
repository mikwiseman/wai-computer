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

from app.config import get_settings
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


async def ocr_pdf(data: bytes, *, model: str | None = None) -> str:
    """OCR a (scanned) PDF via the vision LLM.

    Returns the extracted text (``""`` if the document genuinely has none).
    Raises :class:`OcrError` on an API failure / refusal — never a silent empty.
    """
    if not data:
        return ""
    settings = get_settings()
    client = get_openai_client()
    encoded = base64.b64encode(data).decode("ascii")
    try:
        response = await client.responses.create(
            model=model or settings.openai_llm_model,
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
        logger.warning("pdf OCR failed error_type=%s", type(exc).__name__)
        raise OcrError(f"OCR request failed: {type(exc).__name__}") from exc

    try:
        return response_output_text(response)
    except OpenAIResponseError:
        # The model returned no text — the document genuinely has none (not an
        # error). The caller treats an empty body as "no readable text".
        return ""


_IMAGE_INSTRUCTION = (
    "You are given a single image. First write one line describing what the image "
    "shows. Then, if the image contains any text, add a line 'Text:' and transcribe "
    "ALL visible text verbatim in reading order (every word, number, label, and "
    "table cell). If there is no text, omit the Text section. Do not summarise, "
    "translate, or add commentary beyond the one-line description."
)

_IMAGE_MIME_ALLOWLIST = {"image/jpeg", "image/png", "image/webp", "image/gif"}


async def ocr_image(
    data: bytes,
    *,
    mime_type: str = "image/jpeg",
    model: str | None = None,
) -> str:
    """Describe + OCR an image via the vision LLM (gpt-5.5).

    Returns a one-line description followed by any transcribed text, so a photo
    can be ingested and summarised like any other content. Raises
    :class:`OcrError` on an API failure — never a silent empty on error.
    """
    if not data:
        return ""
    settings = get_settings()
    client = get_openai_client()
    encoded = base64.b64encode(data).decode("ascii")
    mime = (mime_type or "image/jpeg").split(";")[0].strip().lower()
    if mime not in _IMAGE_MIME_ALLOWLIST:
        mime = "image/jpeg"
    try:
        response = await client.responses.create(
            model=model or settings.openai_llm_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _IMAGE_INSTRUCTION},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime};base64,{encoded}",
                        },
                    ],
                }
            ],
        )
        ensure_response_completed(response, operation="Image OCR")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a typed OcrError
        logger.warning("image OCR failed error_type=%s", type(exc).__name__)
        raise OcrError(f"Image OCR request failed: {type(exc).__name__}") from exc

    try:
        return response_output_text(response).strip()
    except OpenAIResponseError:
        return ""


_ALBUM_INSTRUCTION = (
    "You are given {count} images that the user sent together as one album. "
    "For EACH image, output a section that starts with the line 'Image N:' "
    "(N is its 1-based position), then one line describing what it shows, then "
    "— if it contains any text — a line 'Text:' followed by ALL visible text "
    "transcribed verbatim in reading order. Do not summarise, translate, or "
    "add commentary beyond the one-line descriptions."
)


async def ocr_images(
    images: list[tuple[bytes, str]],
    *,
    model: str | None = None,
) -> str:
    """Describe + OCR an ordered album of images in one vision pass.

    Returns per-image sections (``Image 1: … Text: …``) so an album can be
    ingested as a single material. Raises :class:`OcrError` on an API failure —
    never a silent empty on error. An album with genuinely no content returns "".
    """
    if not images:
        return ""
    settings = get_settings()
    client = get_openai_client()
    content: list[dict[str, str]] = [
        {"type": "input_text", "text": _ALBUM_INSTRUCTION.format(count=len(images))}
    ]
    for data, mime_type in images:
        mime = (mime_type or "image/jpeg").split(";")[0].strip().lower()
        if mime not in _IMAGE_MIME_ALLOWLIST:
            mime = "image/jpeg"
        encoded = base64.b64encode(data).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime};base64,{encoded}",
            }
        )
    try:
        response = await client.responses.create(
            model=model or settings.openai_llm_model,
            input=[{"role": "user", "content": content}],
        )
        ensure_response_completed(response, operation="Album OCR")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a typed OcrError
        logger.warning("album OCR failed error_type=%s", type(exc).__name__)
        raise OcrError(f"Album OCR request failed: {type(exc).__name__}") from exc

    try:
        return response_output_text(response).strip()
    except OpenAIResponseError:
        return ""


_ANSWER_INSTRUCTION = (
    "You are Wai, the user's second-brain assistant. The user sent {count} "
    "image(s) with the message below. Answer that message directly, grounded "
    "ONLY in what the image(s) show. If asked to transcribe or translate, be "
    "verbatim and complete. Reply in the same language as the user's message. "
    "Do not describe the images unless asked — answer the question.\n\n"
    "User's message: {question}"
)


async def answer_about_images(
    images: list[tuple[bytes, str]],
    *,
    question: str,
    model: str | None = None,
) -> str:
    """Answer a user's question about one or more images via the vision LLM.

    ``images`` is a list of ``(data, mime_type)`` pairs in the order the user sent
    them. Raises :class:`OcrError` on an API failure or an empty answer — the
    caller surfaces the failure to the user instead of silently filing the photo.
    """
    if not images or not question.strip():
        raise OcrError("Vision answer requires at least one image and a question")
    settings = get_settings()
    client = get_openai_client()
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": _ANSWER_INSTRUCTION.format(count=len(images), question=question.strip()),
        }
    ]
    for data, mime_type in images:
        mime = (mime_type or "image/jpeg").split(";")[0].strip().lower()
        if mime not in _IMAGE_MIME_ALLOWLIST:
            mime = "image/jpeg"
        encoded = base64.b64encode(data).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime};base64,{encoded}",
            }
        )
    try:
        response = await client.responses.create(
            model=model or settings.openai_llm_model,
            input=[{"role": "user", "content": content}],
        )
        ensure_response_completed(response, operation="Image answer")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a typed OcrError
        logger.warning("image answer failed error_type=%s", type(exc).__name__)
        raise OcrError(f"Image answer request failed: {type(exc).__name__}") from exc

    try:
        answer = response_output_text(response).strip()
    except OpenAIResponseError as exc:
        raise OcrError("Image answer was empty") from exc
    if not answer:
        raise OcrError("Image answer was empty")
    return answer
