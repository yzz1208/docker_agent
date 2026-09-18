from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class WorkflowEvalMetrics:
    case_id: str
    completed: bool
    route_match: bool
    tool_call_exact_match: bool
    runtime_citation_present: bool
    docs_citation_present: bool
    concept_coverage: float

    @property
    def exact_workflow_match(self) -> bool:
        return (
            self.completed
            and self.route_match
            and self.tool_call_exact_match
            and self.runtime_citation_present
            and self.docs_citation_present
            and self.concept_coverage == 1.0
        )


def concept_coverage(
    answer: str,
    groups: tuple[tuple[str, ...], ...],
) -> float:
    """Return the fraction of required concept groups mentioned in an answer."""

    if not groups:
        return 1.0

    folded = answer.casefold()
    matched = sum(
        1
        for alternatives in groups
        if any(term.casefold() in folded for term in alternatives)
    )
    return matched / len(groups)



def missing_concept_groups(
    answer: str,
    groups: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Return required concept groups that are not represented in the answer."""

    folded = answer.casefold()
    return tuple(
        alternatives
        for alternatives in groups
        if not any(term.casefold() in folded for term in alternatives)
    )


def summarize_workflow_metrics(
    metrics: list[WorkflowEvalMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "cases": 0,
            "completion_rate": 0.0,
            "route_accuracy": 0.0,
            "tool_call_exact_match_accuracy": 0.0,
            "runtime_citation_rate": 0.0,
            "docs_citation_rate": 0.0,
            "mean_concept_coverage": 0.0,
            "exact_workflow_accuracy": 0.0,
        }

    return {
        "cases": len(metrics),
        "completion_rate": mean(1.0 if item.completed else 0.0 for item in metrics),
        "route_accuracy": mean(1.0 if item.route_match else 0.0 for item in metrics),
        "tool_call_exact_match_accuracy": mean(
            1.0 if item.tool_call_exact_match else 0.0 for item in metrics
        ),
        "runtime_citation_rate": mean(
            1.0 if item.runtime_citation_present else 0.0 for item in metrics
        ),
        "docs_citation_rate": mean(
            1.0 if item.docs_citation_present else 0.0 for item in metrics
        ),
        "mean_concept_coverage": mean(item.concept_coverage for item in metrics),
        "exact_workflow_accuracy": mean(
            1.0 if item.exact_workflow_match else 0.0 for item in metrics
        ),
    }
