from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class DynamicWorkflowEvalMetrics:
    case_id: str
    completed: bool
    route_match: bool
    tool_sequence_match: bool
    finish_present: bool
    step_limit_ok: bool
    no_repeated_tools: bool
    runtime_citation_present: bool
    docs_citation_present: bool
    concept_coverage: float

    @property
    def exact_dynamic_workflow_match(self) -> bool:
        return (
            self.completed
            and self.route_match
            and self.tool_sequence_match
            and self.finish_present
            and self.step_limit_ok
            and self.no_repeated_tools
            and self.runtime_citation_present
            and self.docs_citation_present
            and self.concept_coverage == 1.0
        )


def summarize_dynamic_workflow_metrics(
    metrics: list[DynamicWorkflowEvalMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "cases": 0,
            "completion_rate": 0.0,
            "route_accuracy": 0.0,
            "tool_sequence_accuracy": 0.0,
            "finish_rate": 0.0,
            "step_limit_pass_rate": 0.0,
            "no_repeat_tool_rate": 0.0,
            "runtime_citation_rate": 0.0,
            "docs_citation_rate": 0.0,
            "mean_concept_coverage": 0.0,
            "exact_dynamic_workflow_accuracy": 0.0,
        }

    return {
        "cases": len(metrics),
        "completion_rate": mean(1.0 if item.completed else 0.0 for item in metrics),
        "route_accuracy": mean(1.0 if item.route_match else 0.0 for item in metrics),
        "tool_sequence_accuracy": mean(
            1.0 if item.tool_sequence_match else 0.0 for item in metrics
        ),
        "finish_rate": mean(1.0 if item.finish_present else 0.0 for item in metrics),
        "step_limit_pass_rate": mean(
            1.0 if item.step_limit_ok else 0.0 for item in metrics
        ),
        "no_repeat_tool_rate": mean(
            1.0 if item.no_repeated_tools else 0.0 for item in metrics
        ),
        "runtime_citation_rate": mean(
            1.0 if item.runtime_citation_present else 0.0 for item in metrics
        ),
        "docs_citation_rate": mean(
            1.0 if item.docs_citation_present else 0.0 for item in metrics
        ),
        "mean_concept_coverage": mean(item.concept_coverage for item in metrics),
        "exact_dynamic_workflow_accuracy": mean(
            1.0 if item.exact_dynamic_workflow_match else 0.0 for item in metrics
        ),
    }
