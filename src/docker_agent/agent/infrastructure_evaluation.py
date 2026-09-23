from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from docker_agent.agent.infrastructure import InfrastructureRouteDecision


@dataclass(frozen=True, slots=True)
class InfrastructureRouteMetrics:
    case_id: str
    valid: bool
    route_match: bool
    clarification_present_match: bool

    @property
    def exact_match(self) -> bool:
        return (
            self.valid
            and self.route_match
            and self.clarification_present_match
        )


def evaluate_infrastructure_route(
    *,
    case_id: str,
    expected_route: str,
    decision: InfrastructureRouteDecision | None,
) -> InfrastructureRouteMetrics:
    if expected_route not in {"triage", "clarify"}:
        raise ValueError(
            f"unsupported expected infrastructure route: {expected_route!r}"
        )

    if decision is None:
        return InfrastructureRouteMetrics(
            case_id=case_id,
            valid=False,
            route_match=False,
            clarification_present_match=False,
        )

    expects_clarification = expected_route == "clarify"
    return InfrastructureRouteMetrics(
        case_id=case_id,
        valid=True,
        route_match=decision.route == expected_route,
        clarification_present_match=(
            bool(decision.clarification) == expects_clarification
        ),
    )


def summarize_infrastructure_metrics(
    metrics: list[InfrastructureRouteMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "attempts": 0,
            "safe_decision_rate": 0.0,
            "route_accuracy": 0.0,
            "clarification_accuracy": 0.0,
            "exact_match_accuracy": 0.0,
        }

    return {
        "attempts": len(metrics),
        "safe_decision_rate": mean(
            1.0 if item.valid else 0.0 for item in metrics
        ),
        "route_accuracy": mean(
            1.0 if item.route_match else 0.0 for item in metrics
        ),
        "clarification_accuracy": mean(
            1.0 if item.clarification_present_match else 0.0
            for item in metrics
        ),
        "exact_match_accuracy": mean(
            1.0 if item.exact_match else 0.0 for item in metrics
        ),
    }
