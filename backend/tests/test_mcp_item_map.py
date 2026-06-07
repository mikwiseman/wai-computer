"""Unit tests for mapping tool-output records to ingest_item kwargs (no I/O)."""

from datetime import timezone

from app.core.mcp_item_map import (
    dig,
    first_value,
    parse_datetime,
    parse_records,
    record_to_item_kwargs,
)
from app.core.mcp_plan import FetchStep, FieldMap


def test_parse_records_with_path():
    raw = '{"threads": [{"id": "1"}, {"id": "2"}], "next": "x"}'
    recs = parse_records(raw, record_path="threads")
    assert [r["id"] for r in recs] == ["1", "2"]


def test_parse_records_finds_array_without_path():
    raw = '{"messages": [{"id": "a"}], "ok": true}'
    assert parse_records(raw) == [{"id": "a"}]


def test_parse_records_top_level_list_and_single():
    assert parse_records('[{"id": 1}, {"id": 2}]') == [{"id": 1}, {"id": 2}]
    assert parse_records('{"id": 9, "title": "x"}') == [{"id": 9, "title": "x"}]


def test_parse_records_non_json_is_lossless_text():
    assert parse_records("not json at all") == [{"text": "not json at all"}]


def test_parse_records_missing_path_falls_back_to_payload():
    raw = '{"results": [{"id": "z"}]}'
    # recipe pointed at "threads" but payload uses "results"
    assert parse_records(raw, record_path="threads") == [{"id": "z"}]


def test_dig_and_first_value():
    rec = {"a": {"b": "deep"}, "subject": "", "title": "Hello"}
    assert dig(rec, "a.b") == "deep"
    # subject is empty -> skipped; title wins
    assert first_value(rec, ["subject", "title"]) == "Hello"
    assert first_value(rec, ["missing"]) is None


def test_parse_datetime_iso_epoch_rfc():
    iso = parse_datetime("2026-06-01T12:00:00Z")
    assert iso is not None and iso.tzinfo is not None
    # Gmail internalDate: ms epoch as a string
    ms = parse_datetime("1700000000000")
    assert ms is not None and ms.year == 2023
    secs = parse_datetime(1700000000)
    assert secs is not None and secs.year == 2023
    rfc = parse_datetime("Mon, 01 Jun 2026 12:00:00 +0000")
    assert rfc is not None and rfc.tzinfo is not None
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None


def test_record_to_item_kwargs_maps_fields():
    step = FetchStep(
        enumerate_tool="search_threads",
        kind="email",
        field_map=FieldMap(
            title=["subject"],
            body=["plaintext_body", "snippet"],
            occurred_at=["internalDate"],
            source_ref=["id"],
            url=["url"],
        ),
    )
    rec = {
        "id": "thread-7",
        "subject": "Q3 launch",
        "snippet": "let's ship it",
        "internalDate": "1700000000000",
    }
    kw = record_to_item_kwargs(rec, step=step, connection_id="conn1", stream_key="search_threads")
    assert kw["title"] == "Q3 launch"
    assert kw["body"] == "let's ship it"
    assert kw["kind"] == "email"
    assert kw["source_ref"] == "thread-7"
    assert kw["dedup_key"] == "mcp:conn1:search_threads:thread-7"
    assert kw["occurred_at"].astimezone(timezone.utc).year == 2023
    assert kw["metadata"] == rec


def test_record_to_item_kwargs_fallbacks():
    # No mapped body/title/source_ref -> lossless JSON body, first-line title,
    # hashed source_ref (stable).
    step = FetchStep(enumerate_tool="x", kind="mcp_item", field_map=FieldMap(
        title=["nope"], body=["nope"], source_ref=["nope"], occurred_at=[], url=[]))
    rec = {"weird": "shape", "n": 1}
    kw = record_to_item_kwargs(rec, step=step, connection_id="c", stream_key="x")
    assert "weird" in kw["body"]  # JSON dump of the record
    assert kw["title"]  # non-empty
    assert len(kw["source_ref"]) == 32  # stable hash
    # Deterministic across calls
    kw2 = record_to_item_kwargs(rec, step=step, connection_id="c", stream_key="x")
    assert kw["source_ref"] == kw2["source_ref"]
