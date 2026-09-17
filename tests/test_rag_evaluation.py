from docker_agent.rag.evaluation import RetrievalCase, evaluate_case, summarize_metrics
from docker_agent.rag.store import SearchResult


def _result(file_path: str) -> SearchResult:
    return SearchResult(
        chunk_id=f"chunk:{file_path}",
        document_id=f"doc:{file_path}",
        title="Example",
        section_path=["Example"],
        content="content",
        source_url="https://docs.docker.com/example/",
        file_path=file_path,
        distance=0.2,
    )


def test_evaluate_case_tracks_hit_recall_and_rank() -> None:
    case = RetrievalCase(
        case_id="case-1",
        query="query",
        relevant_file_paths=frozenset({"a.md", "b.md"}),
    )
    results = [_result("x.md"), _result("a.md"), _result("y.md"), _result("b.md")]

    metrics = evaluate_case(case, results)

    assert metrics.first_relevant_rank == 2
    assert metrics.hit_at == {1: False, 3: True, 5: True}
    assert metrics.recall_at == {1: 0.0, 3: 0.5, 5: 1.0}
    assert metrics.reciprocal_rank == 0.5


def test_summarize_metrics_averages_cases() -> None:
    first = evaluate_case(
        RetrievalCase("first", "q1", frozenset({"a.md"})),
        [_result("a.md")],
    )
    second = evaluate_case(
        RetrievalCase("second", "q2", frozenset({"b.md"})),
        [_result("x.md"), _result("b.md")],
    )

    summary = summarize_metrics([first, second])

    assert summary.cases == 2
    assert summary.hit_at[1] == 0.5
    assert summary.hit_at[3] == 1.0
    assert summary.recall_at[1] == 0.5
    assert summary.recall_at[3] == 1.0
    assert summary.mrr == 0.75


def test_empty_summary_is_zeroed() -> None:
    summary = summarize_metrics([])

    assert summary.cases == 0
    assert summary.hit_at == {1: 0.0, 3: 0.0, 5: 0.0}
    assert summary.recall_at == {1: 0.0, 3: 0.0, 5: 0.0}
    assert summary.mrr == 0.0
