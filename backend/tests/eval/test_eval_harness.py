"""Unit tests for the accuracy-per-dollar eval scoring (pure, no DB)."""

from types import SimpleNamespace

import pytest

from app.core.cost_model import QueryCost
from tests.eval.brain_eval import (
    QueryOutcome,
    aggregate,
    format_reports,
    mean_reciprocal_rank,
    precision_at_k,
    rank_of_expected,
)
from tests.eval.golden import DISTRACTORS, GOLDEN


def _hit(title: str = "", snippet: str = ""):
    return SimpleNamespace(title=title, snippet=snippet)


def test_rank_of_expected_matches_title_or_snippet_case_insensitive() -> None:
    hits = [
        _hit(title="Lunch"),
        _hit(snippet="we approved the quarterly budget"),
        _hit(title="Gym"),
    ]
    assert rank_of_expected(hits, ["quarterly budget"]) == 2
    assert rank_of_expected(hits, ["nonexistent"]) is None
    assert rank_of_expected([_hit(title="Q3 BUDGET")], ["budget"]) == 1


def test_precision_and_mrr() -> None:
    outs = [
        QueryOutcome("a", 1, QueryCost()),
        QueryOutcome("b", 3, QueryCost()),
        QueryOutcome("c", None, QueryCost()),
    ]
    assert precision_at_k(outs, 5) == pytest.approx(2 / 3)
    assert precision_at_k(outs, 2) == pytest.approx(1 / 3)  # rank 3 excluded at k=2
    assert mean_reciprocal_rank(outs) == pytest.approx((1 / 1 + 1 / 3 + 0) / 3)


def test_aggregate_accuracy_per_dollar_rewards_cheaper_at_equal_accuracy() -> None:
    # Same precision, different cost -> cheaper config has higher acc/$ (the moat).
    cheap = [QueryOutcome("a", 1, QueryCost(embed_tokens=10))] * 2
    pricey = [QueryOutcome("a", 1, QueryCost(embed_tokens=10, llm_in_tokens=100_000))] * 2
    rc = aggregate(cheap, config="cheap")
    rp = aggregate(pricey, config="pricey")
    assert rc.precision_at_k == rp.precision_at_k == 1.0
    assert rc.accuracy_per_dollar > rp.accuracy_per_dollar


def test_format_reports_smoke() -> None:
    report = aggregate([QueryOutcome("a", 1, QueryCost(embed_tokens=10))], config="baseline")
    out = format_reports([report])
    assert "baseline" in out
    assert "acc/$" in out


def test_golden_set_is_bilingual_and_nontrivial() -> None:
    assert {"en", "ru"} <= {g.lang for g in GOLDEN}
    assert len(GOLDEN) >= 6
    assert len(DISTRACTORS) >= 4
    # Every golden source actually contains its own expected substring (sanity).
    for g in GOLDEN:
        haystack = f"{g.seed_title} {g.seed_body}".lower()
        assert any(e.lower() in haystack for e in g.expected), g.id
