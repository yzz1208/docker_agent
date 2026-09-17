import pytest

from docker_agent.rag.reranker import build_rerank_passage, rerank_candidates
from docker_agent.rag.store import HybridSearchResult


class FakeScorer:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, passages))
        return self.scores


def _candidate(chunk_id: str, rrf_score: float) -> HybridSearchResult:
    return HybridSearchResult(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        title=f"Title {chunk_id}",
        section_path=["Root", f"Section {chunk_id}"],
        content=f"Content for {chunk_id}",
        source_url="https://docs.docker.com/example/",
        file_path=f"{chunk_id}.md",
        rrf_score=rrf_score,
        dense_rank=1,
        keyword_rank=2,
        dense_distance=0.2,
        keyword_score=0.8,
    )


def test_build_rerank_passage_keeps_document_structure() -> None:
    passage = build_rerank_passage(_candidate("a", 0.1))

    assert "Document: Title a" in passage
    assert "Section: Root > Section a" in passage
    assert "Content for a" in passage


def test_rerank_candidates_orders_by_cross_encoder_score() -> None:
    candidates = [
        _candidate("rrf-first", 0.9),
        _candidate("reranker-first", 0.1),
        _candidate("middle", 0.5),
    ]
    scorer = FakeScorer([0.2, 0.95, 0.6])

    results = rerank_candidates("query", candidates, scorer, top_k=2)

    assert [item.chunk_id for item in results] == ["reranker-first", "middle"]
    assert results[0].rerank_score == pytest.approx(0.95)
    assert scorer.calls[0][0] == "query"
    assert len(scorer.calls[0][1]) == 3


def test_rerank_candidates_uses_rrf_as_tie_breaker() -> None:
    candidates = [_candidate("high-rrf", 0.8), _candidate("low-rrf", 0.2)]
    scorer = FakeScorer([0.5, 0.5])

    results = rerank_candidates("query", candidates, scorer, top_k=2)

    assert [item.chunk_id for item in results] == ["high-rrf", "low-rrf"]


def test_rerank_candidates_rejects_misaligned_scores() -> None:
    with pytest.raises(ValueError, match="score count"):
        rerank_candidates(
            "query",
            [_candidate("a", 0.5), _candidate("b", 0.4)],
            FakeScorer([0.9]),
        )


def test_rerank_candidates_empty_input_skips_scorer() -> None:
    scorer = FakeScorer([])

    assert rerank_candidates("query", [], scorer) == []
    assert scorer.calls == []
