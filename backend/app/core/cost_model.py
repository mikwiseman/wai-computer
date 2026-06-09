"""Cost model for the brain's accuracy-per-DOLLAR KPI.

The competitive moat vs gbrain / mem0 / mempalace is economic: deliver a more
accurate answer for fewer DOLLARS. To prove (and defend) that, we price every
component of a query path — embedding the query, reranking candidates, and LLM
synthesis — so the eval harness can report accuracy-per-dollar and so no change
ships that raises $/answer without raising accuracy.

Prices are USD per 1M tokens, June 2026 list prices; override via env when they
move. Token counting is a deliberately simple, *consistent* heuristic (chars/4)
— good enough for relative comparisons (rerank on vs off, Wai vs a full-context
baseline); it is not a billing system.
"""

from __future__ import annotations

from dataclasses import dataclass

# USD per 1,000,000 tokens (June 2026 list prices).
EMBED_USD_PER_M = 0.13  # OpenAI text-embedding-3-large
RERANK_USD_PER_M = 0.025  # ZeroEntropy zerank-2 (cheapest reranker, ~50% under Cohere/Voyage)
LLM_IN_USD_PER_M = 0.35  # Cerebras gpt-oss-120b input
LLM_OUT_USD_PER_M = 0.75  # Cerebras gpt-oss-120b output (reasoning tokens bill as output)

_CHARS_PER_TOKEN = 4  # rough but consistent; Cyrillic skews denser, fine for comparison


def estimate_tokens(text: str | None) -> int:
    """Rough, consistent token estimate for cost comparison (not billing)."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def rerank_token_count(query: str, documents: list[str]) -> int:
    """ZeroEntropy/Voyage-style billing: query_tokens * n_docs + sum(doc_tokens)."""
    if not documents:
        return 0
    q = estimate_tokens(query)
    return q * len(documents) + sum(estimate_tokens(d) for d in documents)


@dataclass
class QueryCost:
    """Per-query cost breakdown across the retrieval + synthesis path."""

    embed_tokens: int = 0
    rerank_tokens: int = 0
    llm_in_tokens: int = 0
    llm_out_tokens: int = 0

    @property
    def embed_usd(self) -> float:
        return self.embed_tokens / 1_000_000 * EMBED_USD_PER_M

    @property
    def rerank_usd(self) -> float:
        return self.rerank_tokens / 1_000_000 * RERANK_USD_PER_M

    @property
    def llm_usd(self) -> float:
        return (
            self.llm_in_tokens / 1_000_000 * LLM_IN_USD_PER_M
            + self.llm_out_tokens / 1_000_000 * LLM_OUT_USD_PER_M
        )

    @property
    def total_usd(self) -> float:
        return self.embed_usd + self.rerank_usd + self.llm_usd

    def as_dict(self) -> dict:
        return {
            "embed_tokens": self.embed_tokens,
            "rerank_tokens": self.rerank_tokens,
            "llm_in_tokens": self.llm_in_tokens,
            "llm_out_tokens": self.llm_out_tokens,
            "embed_usd": round(self.embed_usd, 8),
            "rerank_usd": round(self.rerank_usd, 8),
            "llm_usd": round(self.llm_usd, 8),
            "total_usd": round(self.total_usd, 8),
        }


def accuracy_per_dollar(accuracy: float, total_usd: float) -> float:
    """The headline KPI. Accuracy in [0,1]; returns accuracy per USD.

    Guards divide-by-zero (a $0 path — e.g. a fully cached dossier answer — is
    infinitely cost-efficient, reported as +inf so it sorts to the top).
    """
    if total_usd <= 0:
        return float("inf") if accuracy > 0 else 0.0
    return accuracy / total_usd
