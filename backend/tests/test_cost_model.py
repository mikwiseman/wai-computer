"""Unit tests for the accuracy-per-dollar cost model."""

import math

from app.core.cost_model import (
    EMBED_USD_PER_M,
    LLM_OUT_USD_PER_M,
    RERANK_USD_PER_M,
    QueryCost,
    accuracy_per_dollar,
    estimate_tokens,
    rerank_token_count,
)


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens("a" * 40) == 10


def test_rerank_token_count_voyage_style() -> None:
    # query 8 chars -> 2 tokens; 2 docs of 40 chars -> 10 tokens each.
    assert rerank_token_count("a" * 8, ["b" * 40, "c" * 40]) == 2 * 2 + (10 + 10)
    assert rerank_token_count("q", []) == 0


def test_query_cost_breakdown() -> None:
    c = QueryCost(
        embed_tokens=1_000_000,
        rerank_tokens=1_000_000,
        llm_in_tokens=1_000_000,
        llm_out_tokens=1_000_000,
    )
    assert math.isclose(c.embed_usd, EMBED_USD_PER_M)
    assert math.isclose(c.rerank_usd, RERANK_USD_PER_M)
    assert math.isclose(c.total_usd, c.embed_usd + c.rerank_usd + c.llm_usd)
    assert c.as_dict()["total_usd"] > 0


def test_accuracy_per_dollar() -> None:
    assert accuracy_per_dollar(1.0, 0.0) == float("inf")  # cached/$0 path
    assert accuracy_per_dollar(0.0, 0.0) == 0.0
    assert math.isclose(accuracy_per_dollar(1.0, 0.5), 2.0)
    # Same accuracy, cheaper path => strictly higher KPI (the moat).
    assert accuracy_per_dollar(0.8, 0.001) > accuracy_per_dollar(0.8, 0.01)


def test_reranker_is_cheap_relative_to_other_components() -> None:
    # zerank-2 is the cheapest per-token component — the accuracy-per-dollar lever.
    assert RERANK_USD_PER_M < EMBED_USD_PER_M < LLM_OUT_USD_PER_M
