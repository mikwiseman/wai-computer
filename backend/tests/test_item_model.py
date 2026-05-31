"""Unit tests for the universal Item / ItemChunk models (Phase 0).

These are metadata-level assertions (no DB required) so they run in the unit
suite and document the contract the rest of the second brain builds on:
- ``items`` is registered on Base.metadata with the expected columns,
- the idempotency constraint ``(user_id, content_hash)`` exists,
- ``embedding`` columns are 1536-dim pgvector columns (parity with segments),
- ``item_chunks`` mirrors segments (item_id + seq + content + embedding).
"""

from pgvector.sqlalchemy import Vector

from app.models import Base, Item, ItemChunk


def test_item_tables_registered() -> None:
    assert "items" in Base.metadata.tables
    assert "item_chunks" in Base.metadata.tables
    assert Item.__tablename__ == "items"
    assert ItemChunk.__tablename__ == "item_chunks"


def test_item_columns_present() -> None:
    cols = Base.metadata.tables["items"].columns
    expected = {
        "id",
        "user_id",
        "source",
        "source_ref",
        "url",
        "kind",
        "title",
        "body",
        "occurred_at",
        "content_hash",
        "simhash",
        "privacy_level",
        "authority_score",
        "salience_score",
        "state",
        "metadata",
        "embedding",
        "folder_id",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(set(cols.keys()))


def test_item_idempotency_constraint() -> None:
    constraint_names = {
        c.name for c in Base.metadata.tables["items"].constraints if c.name
    }
    assert "uq_items_user_content_hash" in constraint_names


def test_item_required_nullability() -> None:
    cols = Base.metadata.tables["items"].columns
    # Provenance + dedup + governance fields are NOT NULL.
    for required in ("user_id", "source", "kind", "content_hash", "state"):
        assert cols[required].nullable is False, required
    # Body / title / url are optional (a forwarded link may have no body yet).
    for optional in ("body", "title", "url", "embedding"):
        assert cols[optional].nullable is True, optional


def test_item_embedding_is_1536_vector() -> None:
    embedding = Base.metadata.tables["items"].columns["embedding"]
    assert isinstance(embedding.type, Vector)
    assert embedding.type.dim == 1536


def test_item_chunk_mirrors_segment() -> None:
    cols = Base.metadata.tables["item_chunks"].columns
    for required in ("id", "item_id", "seq", "content"):
        assert required in cols
    chunk_embedding = cols["embedding"]
    assert isinstance(chunk_embedding.type, Vector)
    assert chunk_embedding.type.dim == 1536
    constraint_names = {
        c.name for c in Base.metadata.tables["item_chunks"].constraints if c.name
    }
    assert "uq_item_chunks_item_seq" in constraint_names
