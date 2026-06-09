"""Cross-encoder reranking (P1) — the accuracy-per-dollar precision lever.

After the hybrid RRF + max-pool first stage, a cross-encoder reads each
(query, chunk) pair JOINTLY and re-scores, so the top few results are reliably
right — which lets Ask synthesize from a handful of dense excerpts instead of the
full pool, cutting input tokens (and $) at equal-or-better accuracy.

Default = ZeroEntropy zerank-2 (what gbrain uses): SOTA accuracy, Russian-native,
cheapest ($0.025/M), and CALIBRATED relevance scores — so a confidence threshold
is a meaningful token-budget gate. Swappable behind the ``Reranker`` protocol
(Cohere/Voyage/Cerebras/self-host drop in). OFF by default; with the flag ON a
vendor error RAISES — no silent fallback (AGENTS.md).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.core.cost_model import rerank_token_count

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return a calibrated relevance score in [0,1] per document, in order."""
        ...


class ZerankReranker:
    """ZeroEntropy zerank-2 over the hosted rerank API."""

    def __init__(
        self, *, api_key: str, base_url: str, model: str, timeout: float = 10.0
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.post(
                "/models/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "documents": documents, "model": self._model},
            )
            resp.raise_for_status()
            data = resp.json()
        # {"results": [{"index": i, "relevance_score": s}, ...]} — order not guaranteed.
        scores = [0.0] * len(documents)
        for row in data.get("results", []):
            idx = row.get("index")
            if isinstance(idx, int) and 0 <= idx < len(documents):
                scores[idx] = float(row.get("relevance_score", row.get("score", 0.0)))
        return scores


def get_reranker(settings: Settings) -> Reranker | None:
    """The configured reranker, or ``None`` when disabled. No silent fallback:
    enabled-without-a-key is a config error and raises."""
    if not settings.reranker_enabled:
        return None
    if not settings.zeroentropy_api_key:
        raise RuntimeError("reranker_enabled is true but zeroentropy_api_key is empty")
    return ZerankReranker(
        api_key=settings.zeroentropy_api_key,
        base_url=settings.zeroentropy_base_url,
        model=settings.reranker_model,
    )


def _blend_weights(rrf_rank: int) -> tuple[float, float]:
    """qmd position-aware blend (rrf_weight, rerank_weight), ``rrf_rank`` 1-based.

    Trust RRF's exact-match top picks; trust the reranker more further down.
    """
    if rrf_rank <= 3:
        return 0.75, 0.25
    if rrf_rank <= 10:
        return 0.60, 0.40
    return 0.40, 0.60


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


async def rerank_hits(
    query: str,
    hits: list,
    *,
    reranker: Reranker,
    top_k: int,
    confidence_threshold: float,
    text_of: Callable[[Any], str] | None = None,
) -> tuple[list, int]:
    """Rerank ``hits`` (in RRF order) with the position-aware blend, drop chunks
    below the calibrated-confidence threshold (the token-budget gate), and return
    ``(top_k hits, rerank_tokens)``. Never returns empty when given hits."""
    if not hits:
        return [], 0
    extract = text_of or (lambda h: getattr(h, "snippet", "") or "")
    documents = [extract(h) for h in hits]
    scores = await reranker.rerank(query, documents)
    if len(scores) != len(hits):
        raise RuntimeError(f"reranker returned {len(scores)} scores for {len(hits)} documents")

    rrf_norm = _normalize([float(getattr(h, "score", 0.0)) for h in hits])
    blended: list[tuple[float, float, Any]] = []
    for rank, (hit, rerank_score, rrf_n) in enumerate(zip(hits, scores, rrf_norm), start=1):
        w_rrf, w_rerank = _blend_weights(rank)
        blended.append((w_rrf * rrf_n + w_rerank * rerank_score, rerank_score, hit))
    blended.sort(key=lambda t: t[0], reverse=True)

    # Token-budget gate: keep calibrated-relevant hits; never return empty.
    kept = [b for b in blended if b[1] >= confidence_threshold] or blended[:1]
    rerank_tokens = rerank_token_count(query, documents)
    return [b[2] for b in kept[:top_k]], rerank_tokens
