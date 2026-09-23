from __future__ import annotations

from dataclasses import dataclass

import pytest

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationExecutionService,
    DelegationPolicy,
    OrchestrationDecision,
    OrchestrationExecutionError,
    OrchestrationSpecialistExecutionError,
)


@dataclass(frozen=True, slots=True)
class DummyDecision:
    route: str = "dummy"
    reason: str = "dummy"
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


def _service(
    *,
    docker: RecordingAgent | None = None,
    infrastructure: RecordingAgent | None = None,
    max_hops: int = 2,
) -> tuple[DelegationExecutionService, RecordingAgent, RecordingAgent]:
    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)
    docker_agent = docker or RecordingAgent()
    infrastructure_agent = infrastructure or RecordingAgent()
    factory.register("docker_support", lambda: docker_agent)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure_agent,
    )
    return (
        DelegationExecutionService(
            registry=registry,
            factory=factory,
            max_hops=max_hops,
        ),
        docker_agent,
        infrastructure_agent,
    )


def test_clarify_decision_does_not_invoke_any_agent() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="clarify",
        reason="request is ambiguous",
        source_agent_type=None,
        target_agent_type=None,
        capability=None,
        clarification="你希望排查容器还是服务故障？",
    )

    result = service.execute(
        "帮我看看系统怎么了",
        decision=decision,
    )

    assert result.executed is False
    assert result.agent_type is None
    assert result.turn is None
    assert result.context.hop_count == 0
    assert docker.questions == []
    assert infrastructure.questions == []


def test_direct_decision_invokes_exactly_one_selected_specialist() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="direct",
        reason="needs Docker runtime evidence",
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        clarification=None,
    )

    result = service.execute(
        "  web-1 当前内存是多少？  ",
        decision=decision,
    )

    assert result.executed is True
    assert result.agent_type == "docker_support"
    assert result.current_agent_type == "docker_support"
    assert result.context.hop_count == 0
    assert result.turn is docker.turn
    assert result.request_envelope is None
    assert result.result_envelope is not None
    assert result.result_envelope.agent_type == "docker_support"
    assert result.result_envelope.summary == "public specialist answer"
    assert docker.questions == ["web-1 当前内存是多少？"]
    assert infrastructure.questions == []


def test_direct_decision_can_keep_current_specialist() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="direct",
        reason="current specialist owns documentation QA",
        source_agent_type="docker_support",
        target_agent_type="docker_support",
        capability="documentation_qa",
        clarification=None,
    )

    result = service.execute(
        "Docker volume 和 bind mount 有什么区别？",
        decision=decision,
    )

    assert result.agent_type == "docker_support"
    assert docker.questions == ["Docker volume 和 bind mount 有什么区别？"]
    assert infrastructure.questions == []


def test_delegate_appends_handoff_then_invokes_target_once() -> None:
    service, docker, infrastructure = _service()
    context = DelegationContext(
        original_query="checkout 服务持续失败"
    )
    decision = OrchestrationDecision(
        action="delegate",
        reason="failure is broader than one container",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )

    result = service.execute(
        "容器本身正常，但 checkout 服务仍持续 503。",
        decision=decision,
        context=context,
    )

    assert result.executed is True
    assert result.agent_type == "infrastructure_troubleshooter"
    assert result.context.hop_count == 1
    handoff = result.context.handoffs[0]
    assert handoff.source_agent_type == "docker_support"
    assert handoff.target_agent_type == "infrastructure_troubleshooter"
    assert handoff.capability == "incident_triage"
    assert result.request_envelope is not None
    assert result.request_envelope.source_agent_type == "docker_support"
    assert result.request_envelope.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert result.request_envelope.current_user_message == (
        "容器本身正常，但 checkout 服务仍持续 503。"
    )
    assert result.result_envelope is not None
    assert result.result_envelope.agent_type == (
        "infrastructure_troubleshooter"
    )
    assert docker.questions == []
    assert len(infrastructure.questions) == 1
    delegated_input = infrastructure.questions[0]
    assert "Original user query:\ncheckout 服务持续失败" in delegated_input
    assert (
        "Current user message:\n"
        "容器本身正常，但 checkout 服务仍持续 503。"
        in delegated_input
    )
    assert "source_agent_type: docker_support" in delegated_input
    assert (
        "target_agent_type: infrastructure_troubleshooter"
        in delegated_input
    )


def test_delegate_carries_only_explicit_public_prior_result() -> None:
    service, docker, infrastructure = _service()
    context = DelegationContext(
        original_query="checkout 服务持续失败"
    )
    decision = OrchestrationDecision(
        action="delegate",
        reason="needs service triage",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )
    from docker_agent.orchestration import SpecialistResultEnvelope

    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="container inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常，但服务仍然返回 503。",
    )

    result = service.execute(
        "继续排查服务故障",
        decision=decision,
        context=context,
        explicit_user_clarification="影响生产环境 checkout-api。",
        prior_specialist_result=prior,
    )

    assert result.request_envelope is not None
    assert result.request_envelope.prior_specialist_result is prior
    delegated_input = infrastructure.questions[0]
    assert "影响生产环境 checkout-api。" in delegated_input
    assert "容器运行正常，但服务仍然返回 503。" in delegated_input
    assert "raw tool output" not in delegated_input.lower()
    assert docker.questions == []


def test_delegate_rejects_prior_result_from_wrong_source() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="delegate",
        reason="needs service triage",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )
    from docker_agent.orchestration import SpecialistResultEnvelope

    wrong_source = SpecialistResultEnvelope(
        agent_type="infrastructure_troubleshooter",
        route="triage",
        reason="already triaged",
        needs_clarification=False,
        clarification=None,
        summary="summary",
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="must belong to the source Agent",
    ):
        service.execute(
            "继续排查",
            decision=decision,
            context=DelegationContext(original_query="服务异常"),
            prior_specialist_result=wrong_source,
        )

    assert docker.questions == []
    assert infrastructure.questions == []


def test_execution_revalidates_delegate_loop_before_factory_call() -> None:
    service, docker, infrastructure = _service(max_hops=3)
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry, max_hops=3)
    context = policy.delegate(
        DelegationContext(original_query="服务持续失败"),
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="initial owner",
    )
    context = policy.delegate(
        context,
        source_agent_type="infrastructure_troubleshooter",
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        reason="inspect runtime",
    )
    decision = OrchestrationDecision(
        action="delegate",
        reason="return to incident triage",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="already appears in delegation trace",
    ):
        service.execute(
            "继续分析服务级故障",
            decision=decision,
            context=context,
        )

    assert docker.questions == []
    assert infrastructure.questions == []


def test_execution_enforces_hop_limit_before_specialist_call() -> None:
    service, docker, infrastructure = _service(max_hops=1)
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry, max_hops=2)
    context = policy.delegate(
        DelegationContext(original_query="服务异常"),
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        reason="inspect runtime first",
    )
    decision = OrchestrationDecision(
        action="delegate",
        reason="needs service triage",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="hop limit 1 reached",
    ):
        service.execute(
            "容器正常但服务仍 503",
            decision=decision,
            context=context,
        )

    assert docker.questions == []
    assert infrastructure.questions == []


def test_direct_decision_rejects_unsupported_capability_before_execution() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="direct",
        reason="inspect runtime",
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="runtime_diagnostics",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="does not expose capability",
    ):
        service.execute("检查容器状态", decision=decision)

    assert docker.questions == []
    assert infrastructure.questions == []


def test_context_owner_requires_matching_decision_source() -> None:
    service, _, _ = _service()
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)
    context = policy.delegate(
        DelegationContext(original_query="服务异常"),
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="initial owner",
    )
    decision = OrchestrationDecision(
        action="direct",
        reason="continue triage",
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="decision source is required",
    ):
        service.execute(
            "继续排查",
            decision=decision,
            context=context,
        )


def test_specialist_failure_is_wrapped_with_target_identity() -> None:
    failing = RecordingAgent(error=RuntimeError("provider down"))
    service, _, _ = _service(docker=failing)
    decision = OrchestrationDecision(
        action="direct",
        reason="needs runtime evidence",
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationSpecialistExecutionError,
        match="docker_support",
    ) as exc_info:
        service.execute("检查 web-1", decision=decision)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert failing.questions == ["检查 web-1"]


def test_service_never_recursively_executes_another_agent_from_turn() -> None:
    clarification_turn = DummyTurn(
        answer=None,
        decision=DummyDecision(
            clarification="请提供容器名称。",
        ),
        needs_clarification=True,
    )
    docker = RecordingAgent(turn=clarification_turn)
    infrastructure = RecordingAgent()
    service, _, _ = _service(
        docker=docker,
        infrastructure=infrastructure,
    )
    decision = OrchestrationDecision(
        action="direct",
        reason="needs Docker runtime evidence",
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        clarification=None,
    )

    result = service.execute("检查 web-1", decision=decision)

    assert result.turn is clarification_turn
    assert result.result_envelope is not None
    assert result.result_envelope.needs_clarification is True
    assert result.result_envelope.clarification == "请提供容器名称。"
    assert docker.questions == ["检查 web-1"]
    assert infrastructure.questions == []


def test_unknown_execution_action_is_rejected_before_factory_call() -> None:
    service, docker, infrastructure = _service()
    decision = OrchestrationDecision(
        action="unknown",  # type: ignore[arg-type]
        reason="bad action",
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        clarification=None,
    )

    with pytest.raises(
        OrchestrationExecutionError,
        match="unsupported orchestration action",
    ):
        service.execute("检查 web-1", decision=decision)

    assert docker.questions == []
    assert infrastructure.questions == []
