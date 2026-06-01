"""Build a comparison table across several Items (schema induction + extraction).

Pipeline (reuses the gpt-5.5 structured-output pattern from summarizer.py):
1. Schema induction — given short digests of the items (+ optional user intent),
   the model proposes 3-8 comparison columns with types and a one-line rationale.
2. Row extraction — for each item, extract the value for each column from its
   text. Missing values are null ("not specified"); never fabricated.

LLM calls are injectable so unit tests don't hit OpenAI.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.observability import add_sentry_breadcrumb, capture_sentry_exception
from app.core.openai_client import get_openai_client
from app.core.openai_responses import ensure_response_completed

logger = logging.getLogger(__name__)
settings = get_settings()

# Cap item body sent to the model per item (keep token cost bounded).
_ITEM_DIGEST_CHARS = 4000
MAX_COLUMNS = 8


class ComparisonError(Exception):
    """Comparison generation failed."""


# --- Structured-output schemas ---------------------------------------------


class _Column(BaseModel):
    name: str
    type: Literal["text", "number", "boolean", "category", "date"]


class _ColumnSchema(BaseModel):
    columns: list[_Column] = Field(max_length=MAX_COLUMNS)
    rationale: str


class _RowValue(BaseModel):
    column: str
    value: str | None  # null = not specified; stringified for uniform JSON


class _RowSchema(BaseModel):
    values: list[_RowValue]


# --- Inputs / outputs ------------------------------------------------------


@dataclass
class ComparisonItem:
    """Minimal view of an item for comparison."""

    item_id: str
    title: str
    text: str  # summary or body


@dataclass
class ComparisonResult:
    columns: list[dict]  # [{"name","type"}]
    rows: list[dict]  # [{"item_id","title","values":{col:val|None}}]
    rationale: str


SchemaInducer = Callable[..., Awaitable[_ColumnSchema]]
RowExtractor = Callable[..., Awaitable[_RowSchema]]


def _digest(item: ComparisonItem) -> str:
    return f"[{item.item_id}] {item.title}\n{item.text[:_ITEM_DIGEST_CHARS]}"


async def _induce_columns(items: list[ComparisonItem], intent: str | None) -> _ColumnSchema:
    prompt = (
        "You are designing a comparison table across the items below. Propose "
        f"3-{MAX_COLUMNS} columns that best differentiate them, each with a type "
        "(text/number/boolean/category/date). Pick columns that apply to MOST "
        "items; prefer concrete, comparable attributes over vague ones. Give a "
        "one-line rationale.\n"
    )
    if intent:
        prompt += f"\nThe user wants to compare them by: {intent}\n"
    prompt += "\nItems:\n" + "\n\n".join(_digest(it) for it in items)

    client = get_openai_client()
    response = await client.responses.parse(
        model=settings.openai_llm_model,
        input=prompt,
        text_format=_ColumnSchema,
        reasoning={"effort": "medium"},
        max_output_tokens=2048,
    )
    ensure_response_completed(response, operation="Comparison schema induction")
    if response.output_parsed is None:
        raise ComparisonError("No parsed column schema")
    return response.output_parsed


async def _extract_row(item: ComparisonItem, columns: list[_Column]) -> _RowSchema:
    col_lines = "\n".join(f"- {c.name} ({c.type})" for c in columns)
    prompt = (
        "Extract this item's value for EACH column below. If the item does not "
        "specify a column, return null for it — do NOT guess or invent. Keep "
        "values short.\n\nColumns:\n"
        f"{col_lines}\n\nItem:\n{_digest(item)}"
    )
    client = get_openai_client()
    response = await client.responses.parse(
        model=settings.openai_llm_model,
        input=prompt,
        text_format=_RowSchema,
        reasoning={"effort": "low"},
        max_output_tokens=2048,
    )
    ensure_response_completed(response, operation="Comparison row extraction")
    if response.output_parsed is None:
        raise ComparisonError("No parsed row for item " + item.item_id)
    return response.output_parsed


async def build_comparison(
    items: list[ComparisonItem],
    *,
    intent: str | None = None,
    inducer: SchemaInducer | None = None,
    row_extractor: RowExtractor | None = None,
) -> ComparisonResult:
    """Induce columns, then extract each item's row. Needs >= 2 items."""
    if len(items) < 2:
        raise ComparisonError("Need at least 2 items to compare")

    add_sentry_breadcrumb(
        category="comparison",
        message="Building comparison",
        data={"item_count": len(items)},
    )
    induce = inducer or _induce_columns
    extract = row_extractor or _extract_row

    try:
        schema = await induce(items, intent)
    except ComparisonError:
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        raise ComparisonError(f"Schema induction failed: {exc}") from exc

    columns = schema.columns
    col_names = [c.name for c in columns]

    rows: list[dict] = []
    for item in items:
        try:
            row = await extract(item, columns)
        except ComparisonError:
            raise
        except Exception as exc:  # noqa: BLE001
            capture_sentry_exception(exc)
            raise ComparisonError(f"Row extraction failed: {exc}") from exc
        by_col = {rv.column: rv.value for rv in row.values}
        rows.append(
            {
                "item_id": item.item_id,
                "title": item.title,
                "values": {name: by_col.get(name) for name in col_names},
                "edited": False,
            }
        )

    return ComparisonResult(
        columns=[c.model_dump() for c in columns],
        rows=rows,
        rationale=schema.rationale,
    )


def to_markdown(result: ComparisonResult) -> str:
    """Render a ComparisonResult as a GitHub-flavored markdown table."""
    cols = [c["name"] for c in result.columns]
    header = "| Item | " + " | ".join(cols) + " |"
    sep = "| --- | " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for row in result.rows:
        values = row.get("values") or {}
        cells = [
            str(values.get(c)) if values.get(c) is not None else "—" for c in cols
        ]
        title = str(row.get("title") or "").replace("|", "\\|")
        escaped = " | ".join(c.replace("|", "\\|") for c in cells)
        lines.append(f"| {title} | {escaped} |")
    return "\n".join(lines)
