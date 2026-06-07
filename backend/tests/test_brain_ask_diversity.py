"""Unit tests for per-source-kind excerpt diversity in brain Ask (no I/O)."""

from types import SimpleNamespace

from app.core.brain_ask import _diverse_hits


def _hit(chunk_id, kind, parent):
    return SimpleNamespace(chunk_id=chunk_id, source_kind=kind, parent_id=parent)


def test_kind_cap_reserves_slots_for_other_kinds():
    # 10 distinct emails + 2 distinct meetings; the kind cap (~60% of 5 = 3)
    # stops mail from filling all excerpts, so both meetings get in.
    hits = [_hit(f"i{i}", "item", f"item-{i}") for i in range(10)]
    hits += [_hit(f"r{i}", "recording", f"rec-{i}") for i in range(2)]
    selected = _diverse_hits(hits, limit=5)
    kinds = [h.source_kind for h in selected]
    assert len(selected) == 5
    assert kinds.count("recording") == 2  # meetings not crowded out
    assert kinds.count("item") == 3       # mail capped at ~60%


def test_does_not_waste_slots_when_one_kind():
    # Only items exist -> the second pass fills all slots (no wasted excerpts).
    hits = [_hit(f"i{i}", "item", f"item-{i}") for i in range(8)]
    selected = _diverse_hits(hits, limit=5)
    assert len(selected) == 5
    assert all(h.source_kind == "item" for h in selected)


def test_no_duplicate_chunks():
    hits = [_hit("c1", "item", "p1"), _hit("c1", "item", "p1"), _hit("c2", "recording", "p2")]
    selected = _diverse_hits(hits, limit=5)
    assert len({h.chunk_id for h in selected}) == len(selected)
