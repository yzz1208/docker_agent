from docker_agent.agent.evaluation import (
    AgentPlanExpectation,
    evaluate_agent_plan,
    summarize_agent_metrics,
    summarize_by_phase,
)
from docker_agent.agent.router import AgentRouteDecision


def test_agent_plan_metrics_require_exact_route_tools_and_docs_choice() -> None:
    expected = AgentPlanExpectation(
        route="runtime_tools",
        tools=frozenset({"docker_inspect", "docker_logs"}),
        container_ref="web",
        use_docs=False,
    )
    decision = AgentRouteDecision(
        route="runtime_tools",
        reason="restart diagnosis",
        container_ref="web",
        tools=("docker_logs", "docker_inspect"),
        clarification=None,
        use_docs=False,
    )

    metrics = evaluate_agent_plan(
        case_id="restart",
        phase="initial",
        expected=expected,
        decision=decision,
    )

    assert metrics.valid is True
    assert metrics.route_match is True
    assert metrics.tool_exact_match is True
    assert metrics.container_ref_match is True
    assert metrics.use_docs_match is True
    assert metrics.clarification_present_match is True
    assert metrics.exact_plan_match is True


def test_agent_plan_metrics_mark_invalid_decision_as_failure() -> None:
    expected = AgentPlanExpectation(
        route="docs_only",
        tools=frozenset(),
        container_ref=None,
        use_docs=True,
    )

    metrics = evaluate_agent_plan(
        case_id="docs",
        phase="initial",
        expected=expected,
        decision=None,
    )

    assert metrics.valid is False
    assert metrics.exact_plan_match is False


def test_clarification_presence_is_part_of_exact_plan() -> None:
    expected = AgentPlanExpectation(
        route="clarify",
        tools=frozenset(),
        container_ref=None,
        use_docs=False,
    )
    decision = AgentRouteDecision(
        route="clarify",
        reason="missing container",
        container_ref=None,
        tools=(),
        clarification="请提供容器名。",
        use_docs=False,
    )

    metrics = evaluate_agent_plan(
        case_id="clarify",
        phase="initial",
        expected=expected,
        decision=decision,
    )

    assert metrics.clarification_present_match is True
    assert metrics.exact_plan_match is True


def test_agent_metric_summary_reports_accuracy_and_phase_breakdown() -> None:
    expected = AgentPlanExpectation(
        route="docs_only",
        tools=frozenset(),
        container_ref=None,
        use_docs=True,
    )
    good = evaluate_agent_plan(
        case_id="a",
        phase="initial",
        expected=expected,
        decision=AgentRouteDecision(
            route="docs_only",
            reason="docs",
            container_ref=None,
            tools=(),
            clarification=None,
            use_docs=True,
        ),
    )
    bad = evaluate_agent_plan(
        case_id="b",
        phase="follow_up",
        expected=expected,
        decision=None,
    )

    summary = summarize_agent_metrics([good, bad])
    by_phase = summarize_by_phase([good, bad])

    assert summary["attempts"] == 2
    assert summary["safe_decision_rate"] == 0.5
    assert summary["route_accuracy"] == 0.5
    assert summary["exact_plan_accuracy"] == 0.5
    assert by_phase["initial"]["exact_plan_accuracy"] == 1.0
    assert by_phase["follow_up"]["exact_plan_accuracy"] == 0.0
