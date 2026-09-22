from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class GraphParityMetrics:
    case_id: str
    route_parity: bool
    container_ref_parity: bool
    use_docs_parity: bool
    tool_sequence_parity: bool
    trace_parity: bool
    citation_parity: bool
    clarification_parity: bool
    graph_evidence_labels_match: bool
    legacy_expected_match: bool
    graph_expected_match: bool

    @property
    def exact_parity(self) -> bool:
        return (
            self.route_parity
            and self.container_ref_parity
            and self.use_docs_parity
            and self.tool_sequence_parity
            and self.trace_parity
            and self.citation_parity
            and self.clarification_parity
            and self.graph_evidence_labels_match
        )


def summarize_graph_parity(
    metrics: list[GraphParityMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "cases": 0,
            "route_parity_rate": 0.0,
            "container_ref_parity_rate": 0.0,
            "use_docs_parity_rate": 0.0,
            "tool_sequence_parity_rate": 0.0,
            "trace_parity_rate": 0.0,
            "citation_parity_rate": 0.0,
            "clarification_parity_rate": 0.0,
            "graph_evidence_labels_match_rate": 0.0,
            "legacy_expected_accuracy": 0.0,
            "graph_expected_accuracy": 0.0,
            "exact_parity_rate": 0.0,
        }

    def rate(values: list[bool]) -> float:
        return mean(1.0 if value else 0.0 for value in values)

    return {
        "cases": len(metrics),
        "route_parity_rate": rate([item.route_parity for item in metrics]),
        "container_ref_parity_rate": rate(
            [item.container_ref_parity for item in metrics]
        ),
        "use_docs_parity_rate": rate([item.use_docs_parity for item in metrics]),
        "tool_sequence_parity_rate": rate(
            [item.tool_sequence_parity for item in metrics]
        ),
        "trace_parity_rate": rate([item.trace_parity for item in metrics]),
        "citation_parity_rate": rate([item.citation_parity for item in metrics]),
        "clarification_parity_rate": rate(
            [item.clarification_parity for item in metrics]
        ),
        "graph_evidence_labels_match_rate": rate(
            [item.graph_evidence_labels_match for item in metrics]
        ),
        "legacy_expected_accuracy": rate(
            [item.legacy_expected_match for item in metrics]
        ),
        "graph_expected_accuracy": rate(
            [item.graph_expected_match for item in metrics]
        ),
        "exact_parity_rate": rate([item.exact_parity for item in metrics]),
    }
