from __future__ import annotations

import json
from pathlib import Path

import pytest

from docker_agent.orchestration.decision import OrchestrationDecision
from docker_agent.orchestration.envelope import SpecialistResultEnvelope
from docker_agent.orchestration.evaluation import (
    OrchestrationDecisionExpectation,
    OrchestrationSynthesisExpectation,
    evaluate_orchestration_decision,
    evaluate_orchestration_synthesis,
    summarize_orchestration_by_category,
    summarize_orchestration_decisions,
    summarize_orchestration_synthesis,
)
from docker_agent.orchestration.synthesis import (
    OrchestratedSynthesisResult,
)


def _decision(
    *,
    action: str = "direct",
    source: str | None = None,
    target: str | None = "docker_support",
    capability: str | None = "runtime_diagnostics",
    clarification: str | None = None,
) -> OrchestrationDecision:
    return OrchestrationDecision(
        action=action,  # type: ignore[arg-type]
        reason="test decision",
        source_agent_type=source,
        target_agent_type=target,
        capability=capability,
        clarification=clarification,
    )


def _result(
    agent_type: str,
    *,
    summary: str | None = "public result",
    clarification: str | None = None,
) -> SpecialistResultEnvelope:
    return SpecialistResultEnvelope(
        agent_type=agent_type,
        route="triage",
        reason="test result",
        needs_clarification=clarification is not None,
        clarification=clarification,
        summary=summary,
    )


def test_decision_expectation_rejects_invalid_shapes() -> None:
    with pytest.raises(
        ValueError,
        match="blocked expectation",
    ):
        OrchestrationDecisionExpectation(
            action="direct",
            blocked=True,
        )

    with pytest.raises(
        ValueError,
        match="clarify expectation",
    ):
        OrchestrationDecisionExpectation(
            action="clarify",
            clarification_required=False,
        )

    with pytest.raises(
        ValueError,
        match="requires target and capability",
    ):
        OrchestrationDecisionExpectation(
            action="direct",
        )


def test_decision_metrics_cover_selection_clarification_and_guard() -> None:
    selection = evaluate_orchestration_decision(
        case_id="select-docker",
        category="selection",
        expected=OrchestrationDecisionExpectation(
            action="direct",
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
        ),
        decision=_decision(),
    )
    clarification = evaluate_orchestration_decision(
        case_id="clarify",
        category="clarification",
        expected=OrchestrationDecisionExpectation(
            action="clarify",
            clarification_required=True,
        ),
        decision=_decision(
            action="clarify",
            target=None,
            capability=None,
            clarification="请说明受影响的组件。",
        ),
    )
    guard = evaluate_orchestration_decision(
        case_id="loop",
        category="loop_protection",
        expected=OrchestrationDecisionExpectation(
            blocked=True,
        ),
        decision=None,
        blocked=True,
    )

    assert selection.exact_match is True
    assert selection.specialist_selection_match is True
    assert clarification.exact_match is True
    assert guard.exact_match is True

    summary = summarize_orchestration_decisions(
        [selection, clarification, guard]
    )
    assert summary["attempts"] == 3
    assert summary["safe_decision_rate"] == 1.0
    assert summary["exact_match_accuracy"] == 1.0


def test_decision_metrics_fail_when_guard_is_not_blocked() -> None:
    metrics = evaluate_orchestration_decision(
        case_id="unsafe",
        category="loop_protection",
        expected=OrchestrationDecisionExpectation(
            blocked=True,
        ),
        decision=_decision(
            action="delegate",
            source="docker_support",
            target="infrastructure_troubleshooter",
            capability="incident_triage",
        ),
        blocked=False,
    )

    assert metrics.valid is False
    assert metrics.safety_block_match is False
    assert metrics.exact_match is False


def test_synthesis_metrics_preserve_contributors_and_uncertainty() -> None:
    docker = _result(
        "docker_support",
        summary="container is running",
    )
    infra = _result(
        "infrastructure_troubleshooter",
        summary="service still returns 503",
    )
    synthesis = OrchestratedSynthesisResult(
        original_query="Why is checkout still failing?",
        user_observations=("checkout returns 503",),
        specialist_results=(docker, infra),
        answer="Container health does not establish service health.",
        hypotheses=("dependency failure remains possible",),
        unresolved_uncertainties=("root cause not established",),
        clarification_questions=(),
    )
    metrics = evaluate_orchestration_synthesis(
        case_id="cross-agent",
        category="cross_agent_quality",
        expected=OrchestrationSynthesisExpectation(
            contributing_agents=(
                "docker_support",
                "infrastructure_troubleshooter",
            ),
            answer_required=True,
            clarification_required=False,
            unresolved_uncertainty_required=True,
        ),
        result=synthesis,
    )

    assert metrics.exact_match is True
    summary = summarize_orchestration_synthesis([metrics])
    assert summary["safe_synthesis_rate"] == 1.0
    assert summary["contributing_agents_accuracy"] == 1.0
    assert summary["uncertainty_accuracy"] == 1.0


def test_synthesis_metrics_cover_clarification_precedence() -> None:
    pending = _result(
        "docker_support",
        summary=None,
        clarification="Which container?",
    )
    synthesis = OrchestratedSynthesisResult(
        original_query="Check the container.",
        user_observations=(),
        specialist_results=(pending,),
        answer=None,
        hypotheses=(),
        unresolved_uncertainties=(),
        clarification_questions=("Which container?",),
    )
    metrics = evaluate_orchestration_synthesis(
        case_id="clarification-precedence",
        category="cross_agent_quality",
        expected=OrchestrationSynthesisExpectation(
            contributing_agents=("docker_support",),
            answer_required=False,
            clarification_required=True,
        ),
        result=synthesis,
    )

    assert metrics.exact_match is True


def test_category_summary_keeps_decision_and_synthesis_groups() -> None:
    decision = evaluate_orchestration_decision(
        case_id="selection",
        category="selection",
        expected=OrchestrationDecisionExpectation(
            action="direct",
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
        ),
        decision=_decision(),
    )
    synthesis = evaluate_orchestration_synthesis(
        case_id="synthesis",
        category="cross_agent_quality",
        expected=OrchestrationSynthesisExpectation(
            contributing_agents=("docker_support",),
            answer_required=True,
            clarification_required=False,
        ),
        result=OrchestratedSynthesisResult(
            original_query="question",
            user_observations=(),
            specialist_results=(_result("docker_support"),),
            answer="answer",
            hypotheses=(),
            unresolved_uncertainties=(),
            clarification_questions=(),
        ),
    )

    summary = summarize_orchestration_by_category(
        [decision],
        [synthesis],
    )

    assert set(summary) == {"selection", "cross_agent_quality"}
    assert summary["selection"]["exact_match_accuracy"] == 1.0
    assert (
        summary["cross_agent_quality"]["exact_match_accuracy"]
        == 1.0
    )


def test_orchestration_dataset_has_required_step7_coverage() -> None:
    path = Path("data/eval/orchestration_v1.jsonl")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    ids = [str(row.get("id") or "") for row in rows]
    assert len(rows) >= 20
    assert len(ids) == len(set(ids))
    assert all(ids)

    kinds = {str(row.get("kind") or "") for row in rows}
    assert kinds == {"decision", "guard", "synthesis"}

    categories = {
        str(row.get("category") or "")
        for row in rows
    }
    assert {
        "selection",
        "clarification",
        "delegation",
        "loop_protection",
        "hop_limit",
        "safety_guard",
        "cross_agent_quality",
    } <= categories

    assert {
        "fast-greeting-zh",
        "fast-platform-help-zh",
        "broad-answerable-compose-zh",
        "followup-keep-docker-runtime-zh",
        "followup-keep-infra-triage-zh",
    } <= set(ids)

    for row in rows:
        expected = row.get("expected")
        assert isinstance(expected, dict)
        kind = row["kind"]
        if kind in {"decision", "guard"}:
            OrchestrationDecisionExpectation(
                action=expected.get("action"),
                target_agent_type=expected.get(
                    "target_agent_type"
                ),
                capability=expected.get("capability"),
                clarification_required=(
                    expected.get("clarification_required") is True
                ),
                blocked=expected.get("blocked") is True,
            )
        else:
            agents = expected.get("contributing_agents")
            assert isinstance(agents, list)
            OrchestrationSynthesisExpectation(
                contributing_agents=tuple(
                    str(item) for item in agents
                ),
                answer_required=(
                    expected.get("answer_required") is True
                ),
                clarification_required=(
                    expected.get("clarification_required") is True
                ),
                unresolved_uncertainty_required=(
                    expected.get(
                        "unresolved_uncertainty_required"
                    )
                    is True
                ),
            )
            results = row.get("specialist_results")
            assert isinstance(results, list)
            assert results
