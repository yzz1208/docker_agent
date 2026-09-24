from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationExecutionService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
    SpecialistResultEnvelope,
    run_orchestration_synthesis_graph,
)


@dataclass(frozen=True, slots=True)
class DummyDecision:
    route: str = "dummy"
    reason: str = "dummy specialist result"
    clarification: str | None = None
    use_docs: bool = False


@dataclass(frozen=True, slots=True)
class DummyAnswer:
    answer: str


@dataclass(frozen=True, slots=True)
class DummyTurn:
    answer: DummyAnswer | None
    decision: DummyDecision
    needs_clarification: bool = False


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.user_prompts: list[str] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls += 1
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


class RecordingAgent:
    def __init__(self, turn: DummyTurn) -> None:
        self.turn = turn
        self.questions: list[str] = []

    def handle(self, question: str) -> DummyTurn:
        self.questions.append(question)
        return self.turn


def _turn(
    answer: str,
    *,
    route: str,
    reason: str,
) -> DummyTurn:
    return DummyTurn(
        answer=DummyAnswer(answer),
        decision=DummyDecision(
            route=route,
            reason=reason,
        ),
    )


def _clarify_turn(question: str) -> DummyTurn:
    return DummyTurn(
        answer=None,
        decision=DummyDecision(
            route="clarify",
            reason="specialist needs more context",
            clarification=question,
        ),
        needs_clarification=True,
    )


def _runtime(
    *,
    decision_response: str,
    synthesis_responses: list[str],
    docker_turn: DummyTurn | None = None,
    infrastructure_turn: DummyTurn | None = None,
) -> tuple[
    OrchestrationDecisionModel,
    DelegationExecutionService,
    OrchestratedSynthesisService,
    SequenceModel,
    SequenceModel,
    RecordingAgent,
    RecordingAgent,
]:
    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)

    docker = RecordingAgent(
        docker_turn
        or _turn(
            "容器运行正常。",
            route="runtime_tools",
            reason="runtime inspected",
        )
    )
    infrastructure = RecordingAgent(
        infrastructure_turn
        or _turn(
            "服务仍持续 503，需要继续检查依赖。",
            route="triage",
            reason="service incident triage",
        )
    )
    factory.register("docker_support", lambda: docker)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure,
    )

    decision_model_raw = SequenceModel([decision_response])
    synthesis_model_raw = SequenceModel(synthesis_responses)

    return (
        OrchestrationDecisionModel(
            registry=registry,
            model=decision_model_raw,
            max_hops=2,
        ),
        DelegationExecutionService(
            registry=registry,
            factory=factory,
            max_hops=2,
        ),
        OrchestratedSynthesisService(
            model=synthesis_model_raw,
        ),
        decision_model_raw,
        synthesis_model_raw,
        docker,
        infrastructure,
    )


def test_synthesis_graph_direct_uses_fast_path_without_synthesis() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        decision_raw,
        synthesis_raw,
        docker,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
    )

    result = run_orchestration_synthesis_graph(
        "web-1 当前是否还在运行？",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
    )

    assert result.answer == "容器运行正常。"
    assert result.clarification is None
    assert result.synthesized is False
    assert result.trace == (
        "decision",
        "direct",
        "specialist",
        "complete",
    )
    assert decision_raw.calls == 0
    assert synthesis_raw.calls == 0
    assert docker.questions == ["web-1 当前是否还在运行？"]
    assert infrastructure.questions == []


def test_synthesis_graph_decision_clarify_calls_no_specialist_or_synthesis() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        decision_raw,
        synthesis_raw,
        docker,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"clarify","reason":"scope is ambiguous",'
            '"target_agent_type":null,"capability":null,'
            '"clarification":"请说明是容器问题还是服务故障。"}'
        ),
        synthesis_responses=[],
    )

    result = run_orchestration_synthesis_graph(
        "系统有问题",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
    )

    assert result.answer is None
    assert result.clarification == "请说明是容器问题还是服务故障。"
    assert result.execution is None
    assert result.synthesis is None
    assert result.trace == ("decision", "clarify")
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert infrastructure.questions == []


def test_synthesis_graph_delegate_combines_prior_and_current_public_results() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        decision_raw,
        synthesis_raw,
        docker,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[
            (
                '{"answer":"容器层面正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ],
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )
    context = DelegationContext(
        original_query="checkout 服务持续失败"
    )

    result = run_orchestration_synthesis_graph(
        "容器正常，但 checkout-api 仍持续 503。",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        context=context,
        source_agent_type="docker_support",
        explicit_user_clarification="影响生产环境。",
        user_observations=(
            "checkout-api 持续 503。",
            "影响生产环境。",
        ),
        prior_specialist_result=prior,
    )

    assert result.answer == "容器层面正常，但服务级故障仍存在。"
    assert result.clarification is None
    assert result.synthesized is True
    assert result.synthesis is not None
    assert result.synthesis.contributing_agents == (
        "docker_support",
        "infrastructure_troubleshooter",
    )
    assert result.synthesis.user_observations == (
        "checkout-api 持续 503。",
        "影响生产环境。",
    )
    assert result.context.hop_count == 1
    assert result.trace == (
        "decision",
        "delegate",
        "specialist",
        "synthesis",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 1
    assert docker.questions == []
    assert len(infrastructure.questions) == 1
    delegated_input = infrastructure.questions[0]
    assert "容器运行正常。" in delegated_input
    assert "影响生产环境。" in delegated_input
    assert '"source": "user_reported"' in synthesis_raw.user_prompts[0]


def test_synthesis_graph_specialist_clarification_skips_synthesis() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        _,
        synthesis_raw,
        docker,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service triage",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
        infrastructure_turn=_clarify_turn(
            "请提供受影响的服务名称。"
        ),
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )

    result = run_orchestration_synthesis_graph(
        "继续排查服务故障",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        context=DelegationContext(
            original_query="服务持续失败"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=prior,
    )

    assert result.answer is None
    assert result.clarification == "请提供受影响的服务名称。"
    assert result.synthesized is False
    assert result.synthesis is None
    assert result.trace == (
        "decision",
        "delegate",
        "specialist",
        "complete",
    )
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert len(infrastructure.questions) == 1


def test_synthesis_graph_delegate_without_prior_result_does_not_synthesize() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        _,
        synthesis_raw,
        docker,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service triage",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
    )

    result = run_orchestration_synthesis_graph(
        "检查服务级故障",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        source_agent_type="docker_support",
    )

    assert result.answer == "服务仍持续 503，需要继续检查依赖。"
    assert result.synthesized is False
    assert result.context.hop_count == 1
    assert result.trace == (
        "decision",
        "delegate",
        "specialist",
        "complete",
    )
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert len(infrastructure.questions) == 1


def test_synthesis_graph_prior_clarification_has_precedence_without_model_call() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        _,
        synthesis_raw,
        _,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service triage",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="clarify",
        reason="container identity missing",
        needs_clarification=True,
        clarification="请提供容器名称。",
        summary=None,
    )

    result = run_orchestration_synthesis_graph(
        "继续处理服务故障",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        context=DelegationContext(
            original_query="检查容器与服务"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=prior,
    )

    assert result.answer is None
    assert result.clarification == "请提供容器名称。"
    assert result.synthesized is True
    assert result.synthesis is not None
    assert result.synthesis.needs_clarification is True
    assert synthesis_raw.calls == 0
    assert len(infrastructure.questions) == 1


def test_synthesis_graph_uses_original_query_for_synthesis() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        _,
        synthesis_raw,
        _,
        _,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service triage",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[
            (
                '{"answer":"综合完成。","hypotheses":[],'
                '"unresolved_uncertainties":[]}'
            )
        ],
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )

    run_orchestration_synthesis_graph(
        "这是当前 follow-up 消息",
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        context=DelegationContext(
            original_query="这是原始用户问题"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=prior,
    )

    prompt = synthesis_raw.user_prompts[0]
    assert "Original user question:\n这是原始用户问题" in prompt
    assert "这是当前 follow-up 消息" not in (
        prompt.split("Original user question:\n", 1)[1].split(
            "\n\nUser-reported observations",
            1,
        )[0]
    )
