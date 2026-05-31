"""Content utilities for the universal second brain.

Pure functions (no DB, no network, no new deps) used by the universal
summarizer / ingestion pipeline:

- ``normalize_text`` / ``content_hash`` — a stable SHA-256 idempotency key so
  re-forwarding the same link/article never re-ingests or re-transcribes
  (cost control; honours the Deepgram cost-runaway lesson).
- ``simhash64`` / ``hamming64`` — a 64-bit Charikar SimHash near-duplicate
  fingerprint (wai-brain dedup), stored in ``items.simhash`` (Postgres
  BIGINT). Near-duplicate texts have a small Hamming distance.
- ``chunk_with_header`` — contextual-header chunking: each chunk is prefixed
  with "title › ..." so the lexical + vector index knows what the chunk is
  about (wai-brain contextual-header chunking; lifts retrieval precision).
"""

from __future__ import annotations

import hashlib
import re

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_PARA_RE = re.compile(r"\n\s*\n")
_MASK64 = (1 << 64) - 1

# Near-duplicate threshold for 64-bit SimHash (wai-brain default).
SIMHASH_DUP_MAX_HAMMING = 3


def normalize_text(text: str | None) -> str:
    """Collapse runs of whitespace and strip — stable input for hashing."""
    return _WS_RE.sub(" ", (text or "").strip())


def content_hash(text: str | None) -> str:
    """SHA-256 hex of normalized text. The ingestion idempotency key."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _tokens(text: str | None) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def simhash64(text: str | None) -> int:
    """64-bit Charikar SimHash over token unigrams + bigrams.

    Returns a *signed* 64-bit int (mapped into Postgres BIGINT range). Empty
    text hashes to 0.
    """
    toks = _tokens(text)
    if not toks:
        return 0
    features: dict[str, int] = {}
    for feat in toks:
        features[feat] = features.get(feat, 0) + 1
    for a, b in zip(toks, toks[1:]):
        bigram = f"{a}_{b}"
        features[bigram] = features.get(bigram, 0) + 1

    bits = [0] * 64
    for feat, weight in features.items():
        h = int.from_bytes(
            hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest(), "big"
        )
        for i in range(64):
            bits[i] += weight if (h >> i) & 1 else -weight

    value = 0
    for i in range(64):
        if bits[i] > 0:
            value |= 1 << i
    # Map unsigned 64-bit into signed range for Postgres BIGINT storage.
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def hamming64(a: int, b: int) -> int:
    """Hamming distance between two (possibly signed) 64-bit SimHashes."""
    return bin((a ^ b) & _MASK64).count("1")


def is_near_duplicate(a: int, b: int, max_hamming: int = SIMHASH_DUP_MAX_HAMMING) -> bool:
    """True if two SimHashes are within ``max_hamming`` bits."""
    return hamming64(a, b) <= max_hamming


def _hard_split(text: str, max_chars: int, overlap: int) -> list[str]:
    step = max(1, max_chars - overlap)
    return [text[i : i + max_chars] for i in range(0, len(text), step)]


def chunk_with_header(
    title: str | None,
    body: str | None,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[str]:
    """Split ``body`` into <= ``max_chars`` chunks on paragraph boundaries,
    each prefixed with a "title › " contextual header.

    Oversized paragraphs are hard-split with ``overlap_chars`` overlap so no
    chunk exceeds the budget. Returns ``[]`` for empty body.
    """
    body = (body or "").strip()
    if not body:
        return []
    header = (title or "").strip()
    paragraphs = [p.strip() for p in _PARA_RE.split(body) if p.strip()] or [body]

    raw: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                raw.append(current)
                current = ""
            raw.extend(_hard_split(para, max_chars, overlap_chars))
            continue
        if current and len(current) + 1 + len(para) > max_chars:
            raw.append(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        raw.append(current)

    prefix = f"{header} › " if header else ""
    return [f"{prefix}{chunk.strip()}" for chunk in raw if chunk.strip()]
