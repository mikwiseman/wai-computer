"""Accuracy-per-DOLLAR eval harness for the brain (P0·eval).

The moat is economic: a more accurate answer for fewer dollars than gbrain /
mem0 / mempalace. This harness scores retrieval accuracy AND prices it (via
``cost_model``) so every retrieval change reports BOTH precision and $/query —
the rule is: no change ships that raises $ without raising accuracy.

The scoring + aggregation below is pure and unit-tested (``test_eval_harness``).
The end-to-end runner (``run_against_db``) seeds a corpus and runs real retrieval
— real OpenAI embeddings, plus a ZeroEntropy key for the rerank arm — so it is an
OPS tool you run by hand against a dev DB, not a CI test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.cost_model import QueryCost, accuracy_per_dollar, estimate_tokens


@dataclass
class GoldenQuery:
    """One labelled query: ask ``query``, expect a source containing ``expected``.

    ``seed_title``/``seed_body`` is the source the harness plants so the run is
    reproducible (planted among distractors that retrieval must discriminate).
    """

    id: str
    query: str
    lang: str  # "en" | "ru"
    expected: list[str]
    seed_title: str
    seed_body: str


@dataclass
class QueryOutcome:
    query_id: str
    rank: int | None  # 1-based rank of the first matching hit; None if absent
    cost: QueryCost


@dataclass
class EvalReport:
    config: str
    n: int
    precision_at_k: float
    mrr: float
    avg_usd: float
    accuracy_per_dollar: float
    k: int = 5


# ---- pure scoring -----------------------------------------------------------

def hit_text(hit: Any) -> str:
    return f"{getattr(hit, 'title', '') or ''} {getattr(hit, 'snippet', '') or ''}".lower()


def rank_of_expected(hits: list[Any], expected: list[str]) -> int | None:
    """1-based rank of the first hit whose title/snippet contains any expected
    substring (case-insensitive), or ``None``."""
    needles = [e.lower() for e in expected if e]
    for i, hit in enumerate(hits, start=1):
        text = hit_text(hit)
        if any(n in text for n in needles):
            return i
    return None


def precision_at_k(outcomes: list[QueryOutcome], k: int) -> float:
    if not outcomes:
        return 0.0
    found = sum(1 for o in outcomes if o.rank is not None and o.rank <= k)
    return found / len(outcomes)


def mean_reciprocal_rank(outcomes: list[QueryOutcome]) -> float:
    if not outcomes:
        return 0.0
    return sum((1.0 / o.rank) if o.rank else 0.0 for o in outcomes) / len(outcomes)


def aggregate(outcomes: list[QueryOutcome], *, config: str, k: int = 5) -> EvalReport:
    n = len(outcomes)
    avg_usd = (sum(o.cost.total_usd for o in outcomes) / n) if n else 0.0
    p_at_k = precision_at_k(outcomes, k)
    return EvalReport(
        config=config,
        n=n,
        precision_at_k=p_at_k,
        mrr=mean_reciprocal_rank(outcomes),
        avg_usd=avg_usd,
        accuracy_per_dollar=accuracy_per_dollar(p_at_k, avg_usd),
        k=k,
    )


def format_reports(reports: list[EvalReport]) -> str:
    k = reports[0].k if reports else 5
    header = f"{'config':<28} {'P@' + str(k):>6} {'MRR':>6} {'$/query':>12} {'acc/$':>12}"
    lines = [header, "-" * len(header)]
    for r in reports:
        apd = "inf" if r.accuracy_per_dollar == float("inf") else f"{r.accuracy_per_dollar:,.0f}"
        lines.append(
            f"{r.config:<28} {r.precision_at_k:>6.2f} {r.mrr:>6.2f} {r.avg_usd:>12.6f} {apd:>12}"
        )
    return "\n".join(lines)


# ---- ops runner (real embeddings; run by hand) ------------------------------

async def run_against_db(
    db: Any,
    user_id: Any,
    golden: list[GoldenQuery],
    *,
    settings: Any,
    reranker: Any | None = None,
    k: int = 5,
) -> list[QueryOutcome]:
    """Run each golden query through unified_search (+ optional rerank), measuring
    the rank of the expected source and the per-query cost. Assumes the corpus is
    already seeded (see ``seed_corpus``). Real embeddings — ops use only."""
    from app.core.reranker import rerank_hits
    from app.core.unified_search import unified_search

    outcomes: list[QueryOutcome] = []
    for gq in golden:
        hits = await unified_search(db, user_id, gq.query, limit=max(k, 20), per_parent_limit=1)
        rerank_tokens = 0
        if reranker is not None:
            hits, rerank_tokens = await rerank_hits(
                gq.query, hits, reranker=reranker, top_k=k,
                confidence_threshold=settings.reranker_confidence_threshold,
            )
        cost = QueryCost(embed_tokens=estimate_tokens(gq.query), rerank_tokens=rerank_tokens)
        outcomes.append(
            QueryOutcome(query_id=gq.id, rank=rank_of_expected(hits, gq.expected), cost=cost)
        )
    return outcomes


async def seed_corpus(
    db: Any, user_id: Any, golden: list[GoldenQuery], distractors: list[tuple[str, str]]
) -> None:
    """Plant each golden source + the distractors as items (real embeddings)."""
    from app.core.item_ingest import ingest_item

    for gq in golden:
        await ingest_item(
            db, user_id, source="paste", kind="note", title=gq.seed_title, body=gq.seed_body
        )
    for title, body in distractors:
        await ingest_item(db, user_id, source="paste", kind="note", title=title, body=body)
