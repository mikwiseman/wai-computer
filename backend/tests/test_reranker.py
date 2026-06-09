"""Unit tests for the zerank-2 reranker stage (P1)."""

from types import SimpleNamespace

import pytest

from app.core.reranker import _blend_weights, _normalize, get_reranker, rerank_hits


class FakeReranker:
    def __init__(self, scores_by_text: dict[str, float]) -> None:
        self.scores_by_text = scores_by_text
        self.calls = 0

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.calls += 1
        return [self.scores_by_text.get(d, 0.0) for d in documents]


def _hit(snippet: str, score: float, parent_id: str = "p"):
    return SimpleNamespace(
        snippet=snippet, score=score, source_kind="recording",
        parent_id=parent_id, chunk_id=snippet,
    )


def _settings(**kw):
    base = dict(
        reranker_enabled=False,
        zeroentropy_api_key="",
        zeroentropy_base_url="https://api.zeroentropy.dev/v1",
        reranker_model="zerank-2",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_blend_weights_position_aware() -> None:
    assert _blend_weights(1) == (0.75, 0.25)
    assert _blend_weights(3) == (0.75, 0.25)
    assert _blend_weights(4) == (0.60, 0.40)
    assert _blend_weights(10) == (0.60, 0.40)
    assert _blend_weights(11) == (0.40, 0.60)


def test_normalize() -> None:
    assert _normalize([]) == []
    assert _normalize([5.0, 5.0]) == [1.0, 1.0]
    assert _normalize([0.0, 10.0]) == [0.0, 1.0]


async def test_rerank_promotes_more_relevant_hit() -> None:
    # When RRF can't distinguish two hits (equal fused score), the cross-encoder
    # decides. (By design the qmd blend trusts an UNAMBIGUOUS top RRF pick, so the
    # reranker reshuffles ties + lower ranks rather than clobbering a clear #1.)
    hits = [_hit("weak", 0.05, "a"), _hit("strong", 0.05, "b")]
    fake = FakeReranker({"weak": 0.10, "strong": 0.95})
    out, tokens = await rerank_hits("q", hits, reranker=fake, top_k=10, confidence_threshold=0.0)
    assert out[0].chunk_id == "strong"
    assert tokens > 0
    assert fake.calls == 1


async def test_threshold_drops_low_confidence_keeps_at_least_one() -> None:
    hits = [_hit("a", 0.05, "a"), _hit("b", 0.04, "b")]
    out, _ = await rerank_hits(
        "q", hits, reranker=FakeReranker({"a": 0.9, "b": 0.1}), top_k=10, confidence_threshold=0.5
    )
    assert [h.chunk_id for h in out] == ["a"]  # b dropped below threshold
    out2, _ = await rerank_hits(
        "q", hits, reranker=FakeReranker({"a": 0.1, "b": 0.05}), top_k=10, confidence_threshold=0.5
    )
    assert len(out2) == 1  # all below threshold -> still keep the best one


async def test_rerank_empty_is_noop() -> None:
    out, tokens = await rerank_hits(
        "q", [], reranker=FakeReranker({}), top_k=5, confidence_threshold=0.3
    )
    assert out == [] and tokens == 0


async def test_rerank_mismatched_score_count_raises() -> None:
    class BadReranker:
        async def rerank(self, query, documents):
            return [0.5]  # wrong length

    with pytest.raises(RuntimeError):
        await rerank_hits(
            "q", [_hit("a", 0.1), _hit("b", 0.1)], reranker=BadReranker(),
            top_k=5, confidence_threshold=0.3,
        )


def test_get_reranker_disabled_returns_none() -> None:
    assert get_reranker(_settings()) is None


def test_get_reranker_enabled_without_key_raises() -> None:
    with pytest.raises(RuntimeError):
        get_reranker(_settings(reranker_enabled=True))


def test_get_reranker_enabled_with_key_returns_instance() -> None:
    assert get_reranker(_settings(reranker_enabled=True, zeroentropy_api_key="ze_test")) is not None
