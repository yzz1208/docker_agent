from docker_agent.agent.infrastructure import InfrastructureRouteDecision
from docker_agent.agent.infrastructure_evaluation import (
    evaluate_infrastructure_route,
    summarize_infrastructure_metrics,
)


def test_infrastructure_route_metrics_track_route_and_clarification() -> None:
    triage = evaluate_infrastructure_route(
        case_id="triage",
        expected_route="triage",
        decision=InfrastructureRouteDecision(
            route="triage",
            reason="concrete incident",
            clarification=None,
        ),
    )
    clarify = evaluate_infrastructure_route(
        case_id="clarify",
        expected_route="clarify",
        decision=InfrastructureRouteDecision(
            route="clarify",
            reason="missing symptom",
            clarification="Which symptom is observed?",
        ),
    )

    assert triage.exact_match is True
    assert clarify.exact_match is True

    summary = summarize_infrastructure_metrics([triage, clarify])
    assert summary["attempts"] == 2
    assert summary["route_accuracy"] == 1.0
    assert summary["clarification_accuracy"] == 1.0
    assert summary["exact_match_accuracy"] == 1.0


def test_infrastructure_route_metrics_mark_invalid_decision_as_failure() -> None:
    metrics = evaluate_infrastructure_route(
        case_id="invalid",
        expected_route="triage",
        decision=None,
    )

    assert metrics.valid is False
    assert metrics.exact_match is False
    assert summarize_infrastructure_metrics([metrics])[
        "safe_decision_rate"
    ] == 0.0
