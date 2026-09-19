from docker_agent.agent.dynamic_evaluation import (
    DynamicWorkflowEvalMetrics,
    summarize_dynamic_workflow_metrics,
)


def test_exact_dynamic_workflow_requires_full_trace_quality() -> None:
    metrics = DynamicWorkflowEvalMetrics(
        case_id="memory",
        completed=True,
        route_match=True,
        tool_sequence_match=True,
        finish_present=True,
        step_limit_ok=True,
        no_repeated_tools=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=1.0,
    )

    assert metrics.exact_orchestration_match is True
    assert metrics.exact_dynamic_workflow_match is True


def test_exact_dynamic_workflow_fails_when_sequence_is_wrong() -> None:
    metrics = DynamicWorkflowEvalMetrics(
        case_id="memory",
        completed=True,
        route_match=True,
        tool_sequence_match=False,
        finish_present=True,
        step_limit_ok=True,
        no_repeated_tools=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=1.0,
    )

    assert metrics.exact_orchestration_match is False
    assert metrics.exact_dynamic_workflow_match is False


def test_dynamic_workflow_summary_reports_sequence_and_finish_rates() -> None:
    good = DynamicWorkflowEvalMetrics(
        case_id="good",
        completed=True,
        route_match=True,
        tool_sequence_match=True,
        finish_present=True,
        step_limit_ok=True,
        no_repeated_tools=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=1.0,
    )
    bad = DynamicWorkflowEvalMetrics(
        case_id="bad",
        completed=False,
        route_match=False,
        tool_sequence_match=False,
        finish_present=False,
        step_limit_ok=False,
        no_repeated_tools=False,
        runtime_citation_present=False,
        docs_citation_present=True,
        concept_coverage=0.0,
    )

    summary = summarize_dynamic_workflow_metrics([good, bad])

    assert summary["cases"] == 2
    assert summary["completion_rate"] == 0.5
    assert summary["tool_sequence_accuracy"] == 0.5
    assert summary["finish_rate"] == 0.5
    assert summary["step_limit_pass_rate"] == 0.5
    assert summary["no_repeat_tool_rate"] == 0.5
    assert summary["exact_orchestration_accuracy"] == 0.5
    assert summary["exact_dynamic_workflow_accuracy"] == 0.5


def test_orchestration_can_pass_when_answer_concept_wording_varies() -> None:
    metrics = DynamicWorkflowEvalMetrics(
        case_id="paraphrase",
        completed=True,
        route_match=True,
        tool_sequence_match=True,
        finish_present=True,
        step_limit_ok=True,
        no_repeated_tools=True,
        runtime_citation_present=True,
        docs_citation_present=True,
        concept_coverage=0.67,
    )

    assert metrics.exact_orchestration_match is True
    assert metrics.exact_dynamic_workflow_match is False
