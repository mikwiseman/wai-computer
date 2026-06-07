"""Map an arbitrary MCP tool-output record to ``ingest_item`` kwargs.

Tool results arrive as text that is almost always JSON. We parse it, locate the
array of records, and turn each record into the fields ``ingest_item`` wants
(title / body / occurred_at / source_ref / url / kind) using the step's
:class:`FieldMap` candidate paths (first non-empty wins). Nothing is lost: if no
body field resolves we store the record's JSON; if the output isn't JSON we
store the raw text as one record's body (honest data-preservation, not a silent
failure). The full record is kept in ``metadata`` for cheap structured linking.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.core.mcp_plan import FetchStep


def dig(data: Any, path: str | None) -> Any:
    """Navigate a dotted path (``a.b.c``) into nested dicts/lists. None-safe."""
    if path is None or path == "":
        return data
    node = data
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if node is None:
            return None
    return node


_RECORD_ARRAY_KEYS = (
    "results", "items", "threads", "messages", "files", "events", "data",
    "rows", "records", "chats", "notes", "entries", "transactions",
    "time_entries", "drafts", "labels", "documents", "pages", "list",
)


def parse_records(raw_text: str, record_path: str | None = None) -> list[dict]:
    """Parse tool output into a list of record dicts.

    - If ``record_path`` is given, dig to it first.
    - A list -> its dict elements. A dict with a known array field -> that array.
      A bare dict -> a single record.
    - Non-JSON text -> one record ``{"text": raw_text}`` (lossless, searchable).
    """
    text = (raw_text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [{"text": raw_text}]

    node = dig(data, record_path) if record_path else data
    if node is None and record_path:
        # Recipe pointed at a path this payload doesn't have; fall back to the
        # whole payload so we still surface data rather than silently nothing.
        node = data

    if isinstance(node, list):
        return [r for r in node if isinstance(r, dict)]
    if isinstance(node, dict):
        for key in _RECORD_ARRAY_KEYS:
            value = node.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        return [node]
    return []


def first_value(record: dict, keys: list[str]) -> Any:
    """First non-empty value among candidate keys (dotted paths supported)."""
    for key in keys:
        value = dig(record, key) if "." in key else record.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return None


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def parse_datetime(value: Any) -> datetime | None:
    """Leniently parse a record timestamp to tz-aware UTC. None if unparseable."""
    if value is None:
        return None
    # Epoch (int or numeric string). Gmail internalDate is ms as a string.
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        try:
            num = float(value)
        except (TypeError, ValueError):
            num = None
        if num is not None:
            if num > 1e12:  # milliseconds
                num /= 1000.0
            try:
                return datetime.fromtimestamp(num, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
    if isinstance(value, str):
        s = value.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            pass
    return None


def _stable_id(record: dict) -> str:
    blob = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def record_to_item_kwargs(
    record: dict,
    *,
    step: FetchStep,
    connection_id: str,
    stream_key: str,
) -> dict:
    """Build ``ingest_item`` kwargs for one record. Pure (no I/O)."""
    fm = step.field_map
    source_ref_val = first_value(record, fm.source_ref)
    source_ref = str(source_ref_val) if source_ref_val is not None else _stable_id(record)

    body = _coerce_text(first_value(record, fm.body))
    if not (body and body.strip()):
        body = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True, default=str)

    title = _coerce_text(first_value(record, fm.title))
    if not (title and title.strip()):
        first_line = next((ln for ln in body.splitlines() if ln.strip()), source_ref)
        title = first_line.strip()
    title = title[:500]

    occurred_at = parse_datetime(first_value(record, fm.occurred_at))
    url_val = first_value(record, fm.url)
    url = str(url_val) if isinstance(url_val, str) and url_val.strip() else None

    return {
        "source_ref": source_ref,
        "title": title,
        "body": body,
        "occurred_at": occurred_at,
        "url": url,
        "kind": step.kind,
        "dedup_key": f"mcp:{connection_id}:{stream_key}:{source_ref}",
        "metadata": record,
    }
