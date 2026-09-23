from __future__ import annotations

from dataclasses import dataclass

import pytest

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationExecutionService,
    OrchestrationDecisionModel,
    SpecialistResultEnvelope,
    run_orchestration_execution_graph,
)


@dataclass(frozen=True, slots=True)
class DummyDecision:
    route: str = "dummy"
    reason: str = "dummy specialist result"
    clarification: str | None = None
    use_docs: bool = False


@dataclass(frozen=True, slots=True)
class DummyAnswer:
    answer: str = "public specialist answer"


@dataclass(frozen=True, slots=True)
class DummyTurn:
    answer: DummyAnswer | None = DummyAnswer()
    decision: DummyDecision = DummyDecision()
    needs_clarification: bool = False


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


class RecordingAgent:
    def __init__(
        self,
        *,
        turn: DummyTurn | None = None,
        error: Exception | None = None,
    ) -> None:
        self.turn = turn or DummyTurn()
        self.error = error
        self.questions: list[str] = []

    def handle(self, question: str) -> DummyTurn:
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        return self.turn


def _runtime(
    decision_response: str,
    *,
    docker: RecordingAgent | None = None,
    infrastructure: RecordingAgent | None = None,
) -> tuple[
    OrchestrationDecisionModel,
    DelegationExecutionService,
    SequenceModel,
    RecordingAgent,
    RecordingAgent,
]:
    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)
    docker_agent = docker or RecordingAgent()
    infrastructure_agent = infrastructure or RecordingAgent()
    factory.register("docker_support", lambda: docker_agent)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure_agent,
    )

    model = SequenceModel([decision_response])
    return (
        OrchestrationDecisionModel(
            registry=registry,
            model=model,
            max_hops=2,
        ),
        DelegationExecutionService(
            registry=registry,
            factory=factory,
            max_hops=2,
        ),
        model,
        docker_agent,
        infrastructure_agent,
    )


def test_execution_graph_direct_runs_exactly_one_specialist() -> None:
    (
        decision_model,
        execution_service,
        model,
        docker,
        infrastructure,
    ) = _runtime(
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    result = run_orchestration_execution_graph(
        "web-1 当前内存是多少？",
        decision_model=decision_model,
        execution_service=execution_service,
    )

    assert result.terminal_action == "direct"
    assert result.trace == ("decision", "direct", "specialist")
    assert result.execution is not None
    assert result.execution.executed is True
    assert result.execution.agent_type == "docker_support"
    assert result.execution.request_envelope is None
    assert result.execution.result_envelope is not None
    assert result.execution.result_envelope.summary == (
        "public specialist answer"
    )
    assert result.context.hop_count == 0
    assert model.calls == 1
    assert docker.questions == ["web-1 当前内存是多少？"]
    assert infrastructure.questions == []


def test_execution_graph_clarify_executes_no_specialist() -> None:
    (
        decision_model,
        execution_service,
        model,
        docker,
        infrastructure,
    ) = _runtime(
        '{"action":"clarify","reason":"scope is ambiguous",'
        '"target_agent_type":null,"capability":null,'
        '"clarification":"请说明是容器问题还是服务故障。"}'
    )

    result = run_orchestration_execution_graph(
        "系统有问题",
        decision_model=decision_model,
        execution_service=execution_service,
    )

    assert result.terminal_action == "clarify"
    assert result.trace == ("decision", "clarify")
    assert result.execution is None
    assert result.context.hop_count == 0
    assert model.calls == 1
    assert docker.questions == []
    assert infrastructure.questions == []


def test_execution_graph_delegate_builds_envelope_and_runs_target_once() -> None:
    (
        decision_model,
        execution_service,
        model,
        docker,
        infrastructure,
    ) = _runtime(
        '{"action":"delegate","reason":"service failure remains",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"incident_triage","clarification":null}'
    )
    context = DelegationContext(
        original_query="checkout 服务持续失败"
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="container inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常，但服务仍然返回 503。",
    )

    result = run_orchestration_execution_graph(
        "继续排查 checkout-api 503。",
        decision_model=decision_model,
        execution_service=execution_service,
        context=context,
        source_agent_type="docker_support",
        explicit_user_clarification="影响生产环境。",
        prior_specialist_result=prior,
    )

    assert result.terminal_action == "delegate"
    assert result.trace == ("decision", "delegate", "specialist")
    assert result.execution is not None
    assert result.execution.agent_type == (
        "infrastructure_troubleshooter"
    )
    assert result.context.hop_count == 1
    assert result.execution.request_envelope is not None
    assert result.execution.request_envelope.prior_specialist_result is prior
    assert result.execution.request_envelope.explicit_user_clarification == (
        "影响生产环境。"
    )
    assert docker.questions == []
    assert len(infrastructure.questions) == 1
    delegated_input = infrastructure.questions[0]
    assert "容器运行正常，但服务仍然返回 503。" in delegated_input
    assert "影响生产环境。" in delegated_input
    assert model.calls == 1


def test_execution_graph_does_not_forward_prior_result_on_direct_path() -> None:
    (
        decision_model,
        execution_service,
        _,
        docker,
        infrastructure,
    ) = _runtime(
        '{"action":"direct","reason":"continue runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="prior result",
        needs_clarification=False,
        clarification=None,
        summary="previous public answer",
    )

    result = run_orchestration_execution_graph(
        "继续检查 web-1",
        decision_model=decision_model,
        execution_service=execution_service,
        prior_specialist_result=prior,
    )

    assert result.execution is not None
    assert result.execution.request_envelope is None
    assert docker.questions == ["继续检查 web-1"]
    assert infrastructure.questions == []


def test_execution_graph_preserves_specialist_clarification_result() -> None:
    turn = DummyTurn(
        answer=None,
        decision=DummyDecision(
            route="runtime_tools",
            reason="container identity required",
            clarification="请提供容器名称。",
        ),
        needs_clarification=True,
    )
    docker = RecordingAgent(turn=turn)
    (
        decision_model,
        execution_service,
        _,
        _,
        infrastructure,
    ) = _runtime(
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}',
        docker=docker,
    )

    result = run_orchestration_execution_graph(
        "检查容器状态",
        decision_model=decision_model,
        execution_service=execution_service,
    )

    assert result.execution is not None
    assert result.execution.result_envelope is not None
    assert result.execution.result_envelope.needs_clarification is True
    assert result.execution.result_envelope.clarification == (
        "请提供容器名称。"
    )
    assert infrastructure.questions == []


def test_execution_graph_wraps_specialist_failure_without_retrying() -> None:
    docker = RecordingAgent(error=RuntimeError("provider down"))
    (
        decision_model,
        execution_service,
        _,
        _,
        infrastructure,
    ) = _runtime(
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}',
        docker=docker,
    )

    with pytest.raises(
        RuntimeError,
        match="Agent 'docker_support' failed during orchestration execution",
    ):
        run_orchestration_execution_graph(
            "检查 web-1",
            decision_model=decision_model,
            execution_service=execution_service,
        )

    assert docker.questions == ["检查 web-1"]
    assert infrastructure.questions == []


def test_execution_graph_rejects_empty_input_before_decision_or_agent() -> None:
    (
        decision_model,
        execution_service,
        model,
        docker,
        infrastructure,
    ) = _runtime(
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    with pytest.raises(
        ValueError,
        match="question must not be empty",
    ):
        run_orchestration_execution_graph(
            "   ",
            decision_model=decision_model,
            execution_service=execution_service,
        )

    assert model.calls == 0
    assert docker.questions == []
    assert infrastructure.questions == []
