from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Literal

from docker_agent.orchestration.decision import OrchestrationDecision
from docker_agent.orchestration.synthesis import OrchestratedSynthesisResult

OrchestrationEvalKind = Literal["decision", "guard", "synthesis"]


@dataclass(frozen=True, slots=True)
class OrchestrationDecisionExpectation:
    action: str | None = None
    target_agent_type: str | None = None
    capability: str | None = None
    clarification_required: bool = False
    blocked: bool = False

    def __post_init__(self) -> None:
        if self.blocked:
            if any(
                value is not None
                for value in (
                    self.action,
                    self.target_agent_type,
                    self.capability,
                )
            ):
                raise ValueError(
                    "blocked expectation must not require decision fields"
                )
            if self.clarification_required:
                raise ValueError(
                    "blocked expectation cannot require clarification"
                )
            return

        if self.action not in {"clarify", "direct", "delegate"}:
            raise ValueError(
                "decision expectation requires clarify, direct, or delegate"
            )
        if self.action == "clarify":
            if self.target_agent_type is not None or self.capability is not None:
                raise ValueError(
                    "clarify expectation must not select Agent/capability"
                )
            if not self.clarification_required:
                raise ValueError(
                    "clarify expectation must require clarification"
                )
        else:
            if not self.target_agent_type or not self.capability:
                raise ValueError(
                    "direct/delegate expectation requires target and capability"
                )
            if self.clarification_required:
                raise ValueError(
                    "direct/delegate expectation cannot require clarification"
                )


@dataclass(frozen=True, slots=True)
class OrchestrationDecisionMetrics:
    case_id: str
    category: str
    valid: bool
    action_match: bool
    target_match: bool
    capability_match: bool
    clarification_match: bool
    safety_block_match: bool

    @property
    def specialist_selection_match(self) -> bool:
        return self.target_match and self.capability_match

    @property
    def exact_match(self) -> bool:
        return (
            self.valid
            and self.action_match
            and self.target_match
            and self.capability_match
            and self.clarification_match
            and self.safety_block_match
        )


@dataclass(frozen=True, slots=True)
class OrchestrationSynthesisExpectation:
    contributing_agents: tuple[str, ...]
    answer_required: bool
    clarification_required: bool
    unresolved_uncertainty_required: bool = False

    def __post_init__(self) -> None:
        if not self.contributing_agents:
            raise ValueError("contributing_agents must not be empty")
        if self.answer_required == self.clarification_required:
            raise ValueError(
                "exactly one of answer_required/clarification_required "
                "must be true"
            )
        if (
            self.clarification_required
            and self.unresolved_uncertainty_required
        ):
            raise ValueError(
                "clarification expectation cannot require uncertainty output"
            )


@dataclass(frozen=True, slots=True)
class OrchestrationSynthesisMetrics:
    case_id: str
    category: str
    valid: bool
    contributing_agents_match: bool
    answer_presence_match: bool
    clarification_presence_match: bool
    uncertainty_presence_match: bool

    @property
    def exact_match(self) -> bool:
        return (
            self.valid
            and self.contributing_agents_match
            and self.answer_presence_match
            and self.clarification_presence_match
            and self.uncertainty_presence_match
        )


def evaluate_orchestration_decision(
    *,
    case_id: str,
    category: str,
    expected: OrchestrationDecisionExpectation,
    decision: OrchestrationDecision | None,
    blocked: bool = False,
) -> OrchestrationDecisionMetrics:
    if expected.blocked:
        matched = blocked and decision is None
        return OrchestrationDecisionMetrics(
            case_id=case_id,
            category=category,
            valid=matched,
            action_match=matched,
            target_match=matched,
            capability_match=matched,
            clarification_match=matched,
            safety_block_match=matched,
        )

    if blocked or decision is None:
        return OrchestrationDecisionMetrics(
            case_id=case_id,
            category=category,
            valid=False,
            action_match=False,
            target_match=False,
            capability_match=False,
            clarification_match=False,
            safety_block_match=False,
        )

    clarification_present = bool(decision.clarification)
    return OrchestrationDecisionMetrics(
        case_id=case_id,
        category=category,
        valid=True,
        action_match=decision.action == expected.action,
        target_match=(
            decision.target_agent_type == expected.target_agent_type
        ),
        capability_match=decision.capability == expected.capability,
        clarification_match=(
            clarification_present == expected.clarification_required
        ),
        safety_block_match=True,
    )


def evaluate_orchestration_synthesis(
    *,
    case_id: str,
    category: str,
    expected: OrchestrationSynthesisExpectation,
    result: OrchestratedSynthesisResult | None,
) -> OrchestrationSynthesisMetrics:
    if result is None:
        return OrchestrationSynthesisMetrics(
            case_id=case_id,
            category=category,
            valid=False,
            contributing_agents_match=False,
            answer_presence_match=False,
            clarification_presence_match=False,
            uncertainty_presence_match=False,
        )

    answer_present = bool(result.answer and result.answer.strip())
    clarification_present = result.needs_clarification
    uncertainty_present = bool(result.unresolved_uncertainties)
    return OrchestrationSynthesisMetrics(
        case_id=case_id,
        category=category,
        valid=True,
        contributing_agents_match=(
            result.contributing_agents == expected.contributing_agents
        ),
        answer_presence_match=(
            answer_present == expected.answer_required
        ),
        clarification_presence_match=(
            clarification_present == expected.clarification_required
        ),
        uncertainty_presence_match=(
            uncertainty_present
            == expected.unresolved_uncertainty_required
        ),
    )


def summarize_orchestration_decisions(
    metrics: list[OrchestrationDecisionMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "attempts": 0,
            "safe_decision_rate": 0.0,
            "action_accuracy": 0.0,
            "specialist_selection_accuracy": 0.0,
            "capability_accuracy": 0.0,
            "clarification_accuracy": 0.0,
            "safety_block_accuracy": 0.0,
            "exact_match_accuracy": 0.0,
        }

    return {
        "attempts": len(metrics),
        "safe_decision_rate": _rate(metrics, "valid"),
        "action_accuracy": _rate(metrics, "action_match"),
        "specialist_selection_accuracy": mean(
            1.0 if item.specialist_selection_match else 0.0
            for item in metrics
        ),
        "capability_accuracy": _rate(metrics, "capability_match"),
        "clarification_accuracy": _rate(
            metrics,
            "clarification_match",
        ),
        "safety_block_accuracy": _rate(
            metrics,
            "safety_block_match",
        ),
        "exact_match_accuracy": mean(
            1.0 if item.exact_match else 0.0
            for item in metrics
        ),
    }


def summarize_orchestration_synthesis(
    metrics: list[OrchestrationSynthesisMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "attempts": 0,
            "safe_synthesis_rate": 0.0,
            "contributing_agents_accuracy": 0.0,
            "answer_presence_accuracy": 0.0,
            "clarification_accuracy": 0.0,
            "uncertainty_accuracy": 0.0,
            "exact_match_accuracy": 0.0,
        }

    return {
        "attempts": len(metrics),
        "safe_synthesis_rate": _rate(metrics, "valid"),
        "contributing_agents_accuracy": _rate(
            metrics,
            "contributing_agents_match",
        ),
        "answer_presence_accuracy": _rate(
            metrics,
            "answer_presence_match",
        ),
        "clarification_accuracy": _rate(
            metrics,
            "clarification_presence_match",
        ),
        "uncertainty_accuracy": _rate(
            metrics,
            "uncertainty_presence_match",
        ),
        "exact_match_accuracy": mean(
            1.0 if item.exact_match else 0.0
            for item in metrics
        ),
    }


def summarize_orchestration_by_category(
    decision_metrics: list[OrchestrationDecisionMetrics],
    synthesis_metrics: list[OrchestrationSynthesisMetrics],
) -> dict[str, dict[str, float | int]]:
    categories = sorted(
        {
            item.category
            for item in (*decision_metrics, *synthesis_metrics)
        }
    )
    output: dict[str, dict[str, float | int]] = {}
    for category in categories:
        decisions = [
            item for item in decision_metrics
            if item.category == category
        ]
        syntheses = [
            item for item in synthesis_metrics
            if item.category == category
        ]
        if decisions:
            output[category] = summarize_orchestration_decisions(
                decisions
            )
        else:
            output[category] = summarize_orchestration_synthesis(
                syntheses
            )
    return output


def _rate(
    metrics: list[object],
    attribute: str,
) -> float:
    return mean(
        1.0 if bool(getattr(item, attribute)) else 0.0
        for item in metrics
    )


__all__ = [
    "OrchestrationDecisionExpectation",
    "OrchestrationDecisionMetrics",
    "OrchestrationEvalKind",
    "OrchestrationSynthesisExpectation",
    "OrchestrationSynthesisMetrics",
    "evaluate_orchestration_decision",
    "evaluate_orchestration_synthesis",
    "summarize_orchestration_by_category",
    "summarize_orchestration_decisions",
    "summarize_orchestration_synthesis",
]
