from __future__ import annotations

from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationExecutionService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
    SpecialistResultEnvelope,
)
from docker_agent.orchestration.approval import HumanApprovalPolicy
from docker_agent.orchestration.approval_graph import (
    build_human_approval_orchestration_graph,
    read_human_approval_orchestration,
    resume_human_approval_orchestration,
    start_human_approval_orchestration,
)


@dataclass(frozen=True, slots=True)
class DummyDecision:
    route: str
    reason: str
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

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls += 1
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


def _runtime(
    *,
    decision_response: str,
    synthesis_responses: list[str],
    approval_policy: HumanApprovalPolicy | None = None,
):
    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)
    docker = RecordingAgent(
        _turn(
            "容器运行正常。",
            route="runtime_tools",
            reason="runtime inspected",
        )
    )
    infrastructure = RecordingAgent(
        _turn(
            "服务持续 503，需要继续检查依赖。",
            route="triage",
            reason="service incident",
        )
    )
    factory.register("docker_support", lambda: docker)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure,
    )

    decision_raw = SequenceModel([decision_response])
    synthesis_raw = SequenceModel(synthesis_responses)
    decision_model = OrchestrationDecisionModel(
        registry=registry,
        model=decision_raw,
        max_hops=2,
    )
    execution_service = DelegationExecutionService(
        registry=registry,
        factory=factory,
        max_hops=2,
    )
    synthesis_service = OrchestratedSynthesisService(
        model=synthesis_raw,
    )
    saver = InMemorySaver()
    graph = build_human_approval_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
        approval_policy=approval_policy,
    )
    return (
        graph,
        decision_raw,
        synthesis_raw,
        docker,
        infrastructure,
    )


def _prior_result() -> SpecialistResultEnvelope:
    return SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )


def test_default_delegate_pauses_before_specialist_execution() -> None:
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
    )

    paused = start_human_approval_orchestration(
        graph,
        thread_id="approval-delegate-1",
        question="容器正常，但 checkout-api 仍持续 503。",
        context=DelegationContext(
            original_query="checkout 服务持续失败"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=_prior_result(),
    )

    assert paused.completed is False
    assert paused.next_nodes == ("approval",)
    assert paused.approval_status == "pending"
    assert paused.approval_request is not None
    assert paused.approval_request.action == "delegate"
    assert paused.approval_request.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert paused.approval_request.capability == "incident_triage"
    assert paused.trace == ("decision", "approval_required")
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert infrastructure.questions == []


def test_approval_resume_executes_pending_specialist_and_synthesis_once() -> None:
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[
            (
                '{"answer":"容器正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ],
    )

    start_human_approval_orchestration(
        graph,
        thread_id="approval-delegate-2",
        question="继续排查 checkout-api 503。",
        context=DelegationContext(
            original_query="checkout 服务持续失败"
        ),
        source_agent_type="docker_support",
        user_observations=("checkout-api 持续 503。",),
        prior_specialist_result=_prior_result(),
    )

    resumed = resume_human_approval_orchestration(
        graph,
        thread_id="approval-delegate-2",
        approved=True,
        comment="允许继续跨 Agent 排查。",
    )

    assert resumed.completed is True
    assert resumed.next_nodes == ()
    assert resumed.approval_status == "approved"
    assert resumed.approval_request is None
    assert resumed.approval_comment == "允许继续跨 Agent 排查。"
    assert resumed.answer == "容器正常，但服务级故障仍存在。"
    assert resumed.current_specialist_result is not None
    assert resumed.current_specialist_result.agent_type == (
        "infrastructure_troubleshooter"
    )
    assert resumed.synthesis is not None
    assert resumed.trace == (
        "decision",
        "approval_required",
        "approved",
        "delegate",
        "specialist",
        "synthesis",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 1
    assert docker.questions == []
    assert len(infrastructure.questions) == 1


def test_denied_approval_stops_without_specialist_or_synthesis() -> None:
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
    )

    start_human_approval_orchestration(
        graph,
        thread_id="approval-denied",
        question="继续排查 checkout-api 503。",
        context=DelegationContext(
            original_query="checkout 服务持续失败"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=_prior_result(),
    )

    denied = resume_human_approval_orchestration(
        graph,
        thread_id="approval-denied",
        approved=False,
        comment="先不要继续执行。",
    )

    assert denied.completed is True
    assert denied.approval_status == "denied"
    assert denied.approval_comment == "先不要继续执行。"
    assert denied.answer == "操作未获批准，工作流已停止执行。"
    assert denied.current_specialist_result is None
    assert denied.synthesis is None
    assert denied.trace == (
        "decision",
        "approval_required",
        "denied",
        "approval_denied",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert infrastructure.questions == []


def test_default_direct_read_path_skips_approval_fast_path() -> None:
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
    )

    result = start_human_approval_orchestration(
        graph,
        thread_id="approval-direct-fast",
        question="检查 web-1 当前状态。",
    )

    assert result.completed is True
    assert result.approval_status == "not_required"
    assert result.approval_request is None
    assert result.answer == "容器运行正常。"
    assert result.trace == (
        "decision",
        "approval_skipped",
        "direct",
        "specialist",
        "complete",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == ["检查 web-1 当前状态。"]
    assert infrastructure.questions == []


def test_capability_policy_can_gate_direct_runtime_diagnostics() -> None:
    policy = HumanApprovalPolicy(
        required_actions=frozenset(),
        required_capabilities=frozenset({"runtime_diagnostics"}),
    )
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
        approval_policy=policy,
    )

    paused = start_human_approval_orchestration(
        graph,
        thread_id="approval-direct-gated",
        question="检查 web-1 当前状态。",
    )
    assert paused.completed is False
    assert paused.approval_status == "pending"
    assert paused.approval_request is not None
    assert paused.approval_request.action == "direct"
    assert docker.questions == []

    approved = resume_human_approval_orchestration(
        graph,
        thread_id="approval-direct-gated",
        approved=True,
    )

    assert approved.completed is True
    assert approved.approval_status == "approved"
    assert approved.answer == "容器运行正常。"
    assert approved.trace == (
        "decision",
        "approval_required",
        "approved",
        "direct",
        "specialist",
        "complete",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == ["检查 web-1 当前状态。"]
    assert infrastructure.questions == []


def test_decision_clarification_bypasses_approval_gate() -> None:
    graph, decision_raw, synthesis_raw, docker, infrastructure = _runtime(
        decision_response=(
            '{"action":"clarify","reason":"scope is ambiguous",'
            '"target_agent_type":null,"capability":null,'
            '"clarification":"请说明是容器问题还是服务故障。"}'
        ),
        synthesis_responses=[],
    )

    result = start_human_approval_orchestration(
        graph,
        thread_id="approval-clarify",
        question="系统有问题。",
    )

    assert result.completed is True
    assert result.approval_status is None
    assert result.clarification == "请说明是容器问题还是服务故障。"
    assert result.trace == ("decision", "clarify")
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert infrastructure.questions == []


def test_pending_interrupt_exposes_typed_response_schema_and_can_be_read() -> None:
    graph, _, _, _, _ = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
        synthesis_responses=[],
    )

    start_human_approval_orchestration(
        graph,
        thread_id="approval-schema",
        question="继续排查服务。",
        context=DelegationContext(
            original_query="服务失败"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=_prior_result(),
    )
    result = read_human_approval_orchestration(
        graph,
        thread_id="approval-schema",
    )
    snapshot = graph.get_state(
        {
            "configurable": {
                "thread_id": "approval-schema",
                "checkpoint_ns": "",
            }
        }
    )

    assert result.approval_request is not None
    assert len(snapshot.interrupts) == 1
    assert (
        result.approval_request.interrupt_id
        == snapshot.interrupts[0].id
    )
    schema = result.approval_request.response_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["approved"] == {"type": "boolean"}
    assert properties["comment"] == {"type": "string"}
    assert schema["required"] == ["approved"]


def test_completed_or_non_interrupt_thread_cannot_be_approval_resumed() -> None:
    graph, _, _, _, _ = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
    )

    start_human_approval_orchestration(
        graph,
        thread_id="approval-complete",
        question="检查 web-1。",
    )

    with pytest.raises(
        ValueError,
        match="exactly one pending interrupt",
    ):
        resume_human_approval_orchestration(
            graph,
            thread_id="approval-complete",
            approved=True,
        )


def test_approval_policy_rejects_invalid_configuration() -> None:
    with pytest.raises(
        ValueError,
        match="required_actions",
    ):
        HumanApprovalPolicy(
            required_actions=frozenset({"clarify"}),  # type: ignore[arg-type]
        )

    with pytest.raises(
        ValueError,
        match="required_capabilities",
    ):
        HumanApprovalPolicy(
            required_capabilities=frozenset({"   "}),
        )
