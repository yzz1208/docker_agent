import pytest

from docker_agent.rag.evaluation import (
    RetrievalCase,
    evaluate_case,
    summarize_metrics,
    validate_case_labels,
)
from docker_agent.rag.store import SearchResult


def _result(file_path: str, section: str = "Example") -> SearchResult:
    return SearchResult(
        chunk_id=f"chunk:{file_path}:{section}",
        document_id=f"doc:{file_path}",
        title="Example",
        section_path=["Example", section],
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
    assert metrics.has_section_labels is False
    assert metrics.section_first_relevant_rank is None
    assert metrics.section_hit_at == {}


def test_evaluate_case_tracks_section_rank_separately() -> None:
    case = RetrievalCase(
        case_id="section-case",
        query="daemon unavailable",
        relevant_file_paths=frozenset({"daemon.md"}),
        relevant_section_terms=("Unable to connect",),
    )
    results = [
        _result("daemon.md", "Read the logs"),
        _result("other.md", "Unable to connect"),
        _result("daemon.md", "Unable to connect to the Docker daemon"),
    ]

    metrics = evaluate_case(case, results)

    assert metrics.first_relevant_rank == 1
    assert metrics.section_first_relevant_rank == 3
    assert metrics.section_hit_at == {1: False, 3: True, 5: True}
    assert metrics.section_reciprocal_rank == pytest.approx(1 / 3)


def test_summarize_metrics_averages_document_and_section_cases() -> None:
    first = evaluate_case(
        RetrievalCase(
            "first",
            "q1",
            frozenset({"a.md"}),
            relevant_section_terms=("Target",),
        ),
        [_result("a.md", "Target section")],
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
    assert summary.section_cases == 1
    assert summary.section_hit_at[1] == 1.0
    assert summary.section_mrr == 1.0


def test_validate_case_labels_accepts_existing_file_and_section() -> None:
    cases = [
        RetrievalCase(
            "daemon",
            "query",
            frozenset({"daemon.md"}),
            relevant_section_terms=("Unable to connect",),
        )
    ]
    rows = [
        {
            "file_path": "daemon.md",
            "section_path": ["Troubleshooting", "Unable to connect to the Docker daemon"],
        }
    ]

    validate_case_labels(cases, rows)


def test_validate_case_labels_reports_stale_labels() -> None:
    cases = [
        RetrievalCase(
            "daemon",
            "query",
            frozenset({"missing.md"}),
            relevant_section_terms=("Not there",),
        )
    ]
    rows = [{"file_path": "daemon.md", "section_path": ["Troubleshooting"]}]

    with pytest.raises(ValueError, match="missing files"):
        validate_case_labels(cases, rows)


def test_empty_summary_is_zeroed() -> None:
    summary = summarize_metrics([])

    assert summary.cases == 0
    assert summary.hit_at == {1: 0.0, 3: 0.0, 5: 0.0}
    assert summary.recall_at == {1: 0.0, 3: 0.0, 5: 0.0}
    assert summary.mrr == 0.0
    assert summary.section_cases == 0
    assert summary.section_hit_at == {1: 0.0, 3: 0.0, 5: 0.0}
    assert summary.section_mrr == 0.0
