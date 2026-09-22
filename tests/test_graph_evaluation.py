from docker_agent.graph.evaluation import (
    GraphParityMetrics,
    summarize_graph_parity,
)


def _metrics(**overrides: bool) -> GraphParityMetrics:
    values = {
        "route_parity": True,
        "container_ref_parity": True,
        "use_docs_parity": True,
        "tool_sequence_parity": True,
        "trace_parity": True,
        "citation_parity": True,
        "clarification_parity": True,
        "graph_evidence_labels_match": True,
        "legacy_expected_match": True,
        "graph_expected_match": True,
    }
    values.update(overrides)
    return GraphParityMetrics(case_id="case", **values)


def test_graph_parity_exact_match_requires_all_parity_dimensions() -> None:
    assert _metrics().exact_parity is True
    assert _metrics(trace_parity=False).exact_parity is False


def test_graph_parity_summary_separates_expected_accuracy_from_parity() -> None:
    summary = summarize_graph_parity(
        [
            _metrics(),
            _metrics(
                citation_parity=False,
                graph_expected_match=False,
            ),
        ]
    )

    assert summary["cases"] == 2
    assert summary["route_parity_rate"] == 1.0
    assert summary["citation_parity_rate"] == 0.5
    assert summary["legacy_expected_accuracy"] == 1.0
    assert summary["graph_expected_accuracy"] == 0.5
    assert summary["exact_parity_rate"] == 0.5
