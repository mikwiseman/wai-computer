"""Unit tests for content utilities (dedup fingerprints + chunking)."""

from app.core.content import (
    SIMHASH_DUP_MAX_HAMMING,
    chunk_with_header,
    content_hash,
    hamming64,
    is_near_duplicate,
    normalize_text,
    simhash64,
    with_title_context,
)


def test_normalize_collapses_whitespace() -> None:
    assert normalize_text("  a   b\n\tc ") == "a b c"
    assert normalize_text(None) == ""


def test_content_hash_is_stable_and_whitespace_insensitive() -> None:
    assert content_hash("hello   world") == content_hash("hello world")
    assert content_hash("hello world") == content_hash(" hello world ")
    assert len(content_hash("x")) == 64  # sha256 hex


def test_content_hash_distinguishes_content() -> None:
    assert content_hash("alpha") != content_hash("beta")


def test_simhash_empty_is_zero() -> None:
    assert simhash64("") == 0
    assert simhash64(None) == 0


def test_simhash_identical_text_matches() -> None:
    text = "The quick brown fox jumps over the lazy dog near the river bank."
    assert simhash64(text) == simhash64(text)
    assert hamming64(simhash64(text), simhash64(text)) == 0


def test_simhash_fits_signed_bigint() -> None:
    value = simhash64("a moderately long piece of text " * 20)
    assert -(2**63) <= value <= 2**63 - 1


def test_simhash_near_duplicate_small_distance() -> None:
    base = (
        "Climate policy in 2026 focuses on grid storage, carbon pricing, and "
        "rapid solar deployment across emerging markets and major economies."
    )
    near = base.replace("solar", "wind")  # one token changed
    far = "A recipe for sourdough bread with rye flour and a long cold proof."
    assert hamming64(simhash64(base), simhash64(near)) < hamming64(
        simhash64(base), simhash64(far)
    )


def test_is_near_duplicate_uses_threshold() -> None:
    a = simhash64("the cat sat on the mat in the warm afternoon sun")
    assert is_near_duplicate(a, a)
    assert SIMHASH_DUP_MAX_HAMMING >= 0


def test_chunk_empty_body() -> None:
    assert chunk_with_header("Title", "") == []
    assert chunk_with_header("Title", None) == []


def test_chunk_short_body_single_chunk_with_header() -> None:
    chunks = chunk_with_header("My Article", "A short paragraph of text.")
    assert len(chunks) == 1
    assert chunks[0].startswith("My Article › ")
    assert "A short paragraph" in chunks[0]


def test_chunk_long_body_splits_and_prefixes_each() -> None:
    body = "\n\n".join(f"Paragraph {i} " + ("word " * 60) for i in range(20))
    chunks = chunk_with_header("Doc", body, max_chars=400, overlap_chars=40)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith("Doc › ")
        # header (6) + content; content body capped near max_chars
        assert len(chunk) <= 400 + len("Doc › ") + 5


def test_chunk_without_title_has_no_prefix() -> None:
    chunks = chunk_with_header(None, "Body only, no title here.")
    assert chunks == ["Body only, no title here."]


def test_with_title_context_wraps_for_embedding() -> None:
    # Voice/segment path: embed with the recording's topic; raw transcript stays raw.
    assert with_title_context("Budget meeting", "he agreed") == "Budget meeting › he agreed"
    assert with_title_context(None, "x") == "x"
    assert with_title_context("   ", "x") == "x"  # blank title -> no prefix
    assert with_title_context("  Topic  ", "line") == "Topic › line"  # trimmed
