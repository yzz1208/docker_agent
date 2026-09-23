from __future__ import annotations

import pytest

from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration.decision import (
    OrchestrationDecisionError,
    OrchestrationDecisionModel,
)
from docker_agent.orchestration.delegation import DelegationContext
from docker_agent.orchestration.graph import (
    OrchestrationDecisionGraphResult,
    run_orchestration_decision_graph,
)


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls += 1
        return self.responses.pop(0)


def _decision_model(response: str) -> tuple[
    OrchestrationDecisionModel,
    SequenceModel,
]:
    model = SequenceModel([response])
    return (
        OrchestrationDecisionModel(
            registry=build_agent_registry(),
            model=model,
            max_hops=2,
        ),
        model,
    )


def test_decision_graph_routes_direct_to_terminal_without_execution() -> None:
    decision_model, model = _decision_model(
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    result = run_orchestration_decision_graph(
        "web-1 现在是否还在运行？",
        decision_model=decision_model,
    )

    assert isinstance(result, OrchestrationDecisionGraphResult)
    assert result.decision.action == "direct"
    assert result.decision.target_agent_type == "docker_support"
    assert result.terminal_action == "direct"
    assert result.trace == ("decision", "direct")
    assert result.context.hop_count == 0
    assert model.calls == 1


def test_decision_graph_routes_clarification_to_terminal() -> None:
    decision_model, model = _decision_model(
        '{"action":"clarify","reason":"scope is ambiguous",'
        '"target_agent_type":null,"capability":null,'
        '"clarification":"你希望检查容器还是服务级故障？"}'
    )

    result = run_orchestration_decision_graph(
        "系统好像有问题",
        decision_model=decision_model,
    )

    assert result.decision.action == "clarify"
    assert result.decision.clarification == (
        "你希望检查容器还是服务级故障？"
    )
    assert result.terminal_action == "clarify"
    assert result.trace == ("decision", "clarify")
    assert model.calls == 1


def test_decision_graph_routes_validated_delegate_without_execution() -> None:
    decision_model, model = _decision_model(
        '{"action":"delegate","reason":"service-level incident",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"incident_triage","clarification":null}'
    )
    context = DelegationContext(
        original_query="检查 checkout 服务",
    )

    result = run_orchestration_decision_graph(
        "容器正常，但 checkout-api 仍然持续 503。",
        decision_model=decision_model,
        context=context,
        source_agent_type="docker_support",
    )

    assert result.decision.action == "delegate"
    assert result.decision.source_agent_type == "docker_support"
    assert result.decision.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert result.terminal_action == "delegate"
    assert result.trace == ("decision", "delegate")
    assert result.context == context
    assert result.context.hop_count == 0
    assert model.calls == 1


def test_decision_graph_matches_direct_decision_contract() -> None:
    response = (
        '{"action":"direct","reason":"service incident",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"incident_triage","clarification":null}'
    )
    direct_model, direct_llm = _decision_model(response)
    graph_model, graph_llm = _decision_model(response)
    question = "checkout-api 持续返回 503，依赖超时增加。"

    expected = direct_model.decide(question)
    actual = run_orchestration_decision_graph(
        question,
        decision_model=graph_model,
    )

    assert actual.decision == expected
    assert actual.terminal_action == expected.action
    assert direct_llm.calls == 1
    assert graph_llm.calls == 1


def test_decision_graph_preserves_policy_rejection() -> None:
    decision_model, model = _decision_model(
        '{"action":"delegate","reason":"invalid initial handoff",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="delegate requires a current source Agent",
    ):
        run_orchestration_decision_graph(
            "检查 web-1",
            decision_model=decision_model,
        )

    assert model.calls == 1


def test_decision_graph_rejects_empty_question_before_model_call() -> None:
    decision_model, model = _decision_model(
        '{"action":"direct","reason":"runtime",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    with pytest.raises(
        ValueError,
        match="question must not be empty",
    ):
        run_orchestration_decision_graph(
            "   ",
            decision_model=decision_model,
        )

    assert model.calls == 0


def test_decision_graph_result_rejects_inconsistent_terminal() -> None:
    decision_model, _ = _decision_model(
        '{"action":"direct","reason":"runtime",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )
    decision = decision_model.decide("检查 web-1")

    with pytest.raises(
        ValueError,
        match="terminal_action must match",
    ):
        OrchestrationDecisionGraphResult(
            decision=decision,
            context=DelegationContext(original_query="检查 web-1"),
            terminal_action="clarify",
            trace=("decision", "clarify"),
        )
