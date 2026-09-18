from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from docker_agent.agent.router import AgentRouteDecision


@dataclass(frozen=True, slots=True)
class AgentPlanExpectation:
    route: str
    tools: frozenset[str]
    container_ref: str | None
    use_docs: bool


@dataclass(frozen=True, slots=True)
class AgentEvalCase:
    case_id: str
    question: str
    expected: AgentPlanExpectation
    follow_up_message: str | None = None
    follow_up_expected: AgentPlanExpectation | None = None


@dataclass(frozen=True, slots=True)
class AgentPlanMetrics:
    case_id: str
    phase: str
    valid: bool
    route_match: bool
    tool_exact_match: bool
    container_ref_match: bool
    use_docs_match: bool
    clarification_present_match: bool

    @property
    def exact_plan_match(self) -> bool:
        return (
            self.valid
            and self.route_match
            and self.tool_exact_match
            and self.container_ref_match
            and self.use_docs_match
            and self.clarification_present_match
        )


def evaluate_agent_plan(
    *,
    case_id: str,
    phase: str,
    expected: AgentPlanExpectation,
    decision: AgentRouteDecision | None,
) -> AgentPlanMetrics:
    """Compare one validated router decision with its expected evidence plan."""

    if decision is None:
        return AgentPlanMetrics(
            case_id=case_id,
            phase=phase,
            valid=False,
            route_match=False,
            tool_exact_match=False,
            container_ref_match=False,
            use_docs_match=False,
            clarification_present_match=False,
        )

    expects_clarification = expected.route == "clarify"
    has_clarification = bool(decision.clarification)

    return AgentPlanMetrics(
        case_id=case_id,
        phase=phase,
        valid=True,
        route_match=decision.route == expected.route,
        tool_exact_match=frozenset(decision.tools) == expected.tools,
        container_ref_match=decision.container_ref == expected.container_ref,
        use_docs_match=decision.use_docs == expected.use_docs,
        clarification_present_match=has_clarification == expects_clarification,
    )


def summarize_agent_metrics(
    metrics: list[AgentPlanMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "attempts": 0,
            "safe_decision_rate": 0.0,
            "route_accuracy": 0.0,
            "tool_exact_match_accuracy": 0.0,
            "container_ref_accuracy": 0.0,
            "use_docs_accuracy": 0.0,
            "clarification_accuracy": 0.0,
            "exact_plan_accuracy": 0.0,
        }

    return {
        "attempts": len(metrics),
        "safe_decision_rate": mean(1.0 if item.valid else 0.0 for item in metrics),
        "route_accuracy": mean(1.0 if item.route_match else 0.0 for item in metrics),
        "tool_exact_match_accuracy": mean(
            1.0 if item.tool_exact_match else 0.0 for item in metrics
        ),
        "container_ref_accuracy": mean(
            1.0 if item.container_ref_match else 0.0 for item in metrics
        ),
        "use_docs_accuracy": mean(
            1.0 if item.use_docs_match else 0.0 for item in metrics
        ),
        "clarification_accuracy": mean(
            1.0 if item.clarification_present_match else 0.0 for item in metrics
        ),
        "exact_plan_accuracy": mean(
            1.0 if item.exact_plan_match else 0.0 for item in metrics
        ),
    }


def summarize_by_phase(
    metrics: list[AgentPlanMetrics],
) -> dict[str, dict[str, float | int]]:
    phases = sorted({item.phase for item in metrics})
    return {
        phase: summarize_agent_metrics(
            [item for item in metrics if item.phase == phase]
        )
        for phase in phases
    }
