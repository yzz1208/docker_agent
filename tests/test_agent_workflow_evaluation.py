from docker_agent.agent.workflow_evaluation import (
    WorkflowEvalMetrics,
    concept_coverage,
    summarize_workflow_metrics,
)


def test_concept_coverage_matches_alternative_terms() -> None:
    coverage = concept_coverage(
        "容器因为 OOM 被杀，退出码是 137。",
        (("OOM", "内存不足"), ("137", "exit code 137")),
    )

    assert coverage == 1.0


def test_exact_workflow_requires_all_components() -> None:
    metrics = WorkflowEvalMetrics(
        case_id="oom",
        completed=True,
        route_match=True,
        tool_call_exact_match=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=1.0,
    )

    assert metrics.exact_workflow_match is True


def test_exact_workflow_fails_on_missing_concept() -> None:
    metrics = WorkflowEvalMetrics(
        case_id="oom",
        completed=True,
        route_match=True,
        tool_call_exact_match=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=0.5,
    )

    assert metrics.exact_workflow_match is False


def test_workflow_summary_averages_metrics() -> None:
    good = WorkflowEvalMetrics(
        case_id="good",
        completed=True,
        route_match=True,
        tool_call_exact_match=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=1.0,
    )
    bad = WorkflowEvalMetrics(
        case_id="bad",
        completed=False,
        route_match=False,
        tool_call_exact_match=False,
        runtime_citation_present=False,
        docs_citation_present=True,
        concept_coverage=0.0,
    )

    summary = summarize_workflow_metrics([good, bad])

    assert summary["cases"] == 2
    assert summary["completion_rate"] == 0.5
    assert summary["route_accuracy"] == 0.5
    assert summary["tool_call_exact_match_accuracy"] == 0.5
    assert summary["runtime_citation_rate"] == 0.5
    assert summary["docs_citation_rate"] == 1.0
    assert summary["mean_concept_coverage"] == 0.5
    assert summary["exact_workflow_accuracy"] == 0.5
