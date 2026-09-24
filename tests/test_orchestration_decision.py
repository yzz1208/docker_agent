import pytest

from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationPolicy,
    OrchestrationDecisionError,
    OrchestrationDecisionModel,
)


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


def _model(response: str, *, max_hops: int = 2):
    registry = build_agent_registry()
    fake = SequenceModel([response])
    return (
        OrchestrationDecisionModel(
            registry=registry,
            model=fake,
            max_hops=max_hops,
        ),
        fake,
        registry,
    )


def test_initial_lightweight_chat_skips_orchestration_model() -> None:
    registry = build_agent_registry()
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    decision = orchestrator.decide("介绍一下这个平台")

    assert decision.action == "direct"
    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "chat"
    assert decision.clarification is None
    assert fake.user_prompts == []
    assert fake.system_prompts == []


def test_initial_docker_docs_request_skips_orchestration_model() -> None:
    registry = build_agent_registry()
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    decision = orchestrator.decide(
        "Docker volume 和 bind mount 有什么区别？"
    )

    assert decision.action == "direct"
    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "documentation_qa"
    assert fake.user_prompts == []


def test_initial_runtime_request_routes_directly_to_docker_support() -> None:
    registry = build_agent_registry()
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    decision = orchestrator.decide("web-1 当前 CPU 和内存是多少？")

    assert decision.action == "direct"
    assert decision.source_agent_type is None
    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "runtime_diagnostics"
    assert decision.clarification is None
    assert decision.is_handoff is False
    assert fake.user_prompts == []


def test_initial_incident_routes_directly_to_infrastructure_agent() -> None:
    registry = build_agent_registry()
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    decision = orchestrator.decide(
        "checkout-api 从 10:20 开始持续 503，依赖超时增加。"
    )

    assert decision.action == "direct"
    assert decision.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert decision.capability == "incident_triage"
    assert fake.user_prompts == []


def test_orchestrator_can_request_user_clarification() -> None:
    orchestrator, _, _ = _model(
        '{"action":"clarify","reason":"request is ambiguous",'
        '"target_agent_type":null,"capability":null,'
        '"clarification":"你希望排查 Docker 容器还是服务级故障？"}'
    )

    decision = orchestrator.decide("帮我看看系统怎么了")

    assert decision.action == "clarify"
    assert decision.requires_user_input is True
    assert decision.target_agent_type is None
    assert decision.capability is None
    assert decision.clarification is not None


def test_existing_specialist_can_choose_validated_delegation() -> None:
    orchestrator, fake, _ = _model(
        '{"action":"delegate","reason":"broader service incident",'
        '"target_agent_type":"Infrastructure-Troubleshooter",'
        '"capability":"incident-triage","clarification":null}'
    )

    decision = orchestrator.decide(
        "容器本身正常，但整个 checkout 服务仍持续 503。",
        source_agent_type="Docker-Support",
    )

    assert decision.action == "delegate"
    assert decision.source_agent_type == "docker_support"
    assert decision.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert decision.capability == "incident_triage"
    assert decision.is_handoff is True
    assert '"current_agent_type": "docker_support"' in fake.user_prompts[0]


def test_current_docker_specialist_docs_followup_skips_model() -> None:
    registry = build_agent_registry()
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    decision = orchestrator.decide(
        "Docker volume 和 bind mount 有什么区别？",
        source_agent_type="docker_support",
    )

    assert decision.action == "direct"
    assert decision.source_agent_type == "docker_support"
    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "documentation_qa"
    assert fake.user_prompts == []


def test_current_docker_specialist_incident_can_still_delegate() -> None:
    orchestrator, fake, _ = _model(
        '{"action":"delegate","reason":"service incident",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"incident_triage","clarification":null}'
    )

    decision = orchestrator.decide(
        "容器正常，但 checkout-api 持续 503，依赖超时增加。",
        source_agent_type="docker_support",
    )

    assert decision.action == "delegate"
    assert decision.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert decision.capability == "incident_triage"
    assert len(fake.user_prompts) == 1


def test_direct_action_can_keep_current_specialist() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"current specialist owns capability",'
        '"target_agent_type":"docker_support",'
        '"capability":"documentation_qa","clarification":null}'
    )

    decision = orchestrator.decide(
        "Docker volume 和 bind mount 有什么区别？",
        source_agent_type="docker_support",
    )

    assert decision.action == "direct"
    assert decision.source_agent_type == "docker_support"
    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "documentation_qa"


def test_code_fenced_json_is_accepted() -> None:
    orchestrator, _, _ = _model(
        """```json
{"action":"direct","reason":"needs runtime evidence","target_agent_type":"docker_support","capability":"runtime_diagnostics","clarification":null}
```"""
    )

    decision = orchestrator.decide("检查 web-1 的资源问题")

    assert decision.target_agent_type == "docker_support"
    assert decision.capability == "runtime_diagnostics"


def test_decision_schema_rejects_unexpected_fields() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"runtime","target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null,'
        '"tool":"docker_restart"}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="unexpected fields: tool",
    ):
        orchestrator.decide("检查 web-1")


def test_decision_schema_rejects_missing_fields() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"runtime",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics"}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="missing fields: clarification",
    ):
        orchestrator.decide("检查 web-1")


def test_initial_platform_dispatch_cannot_be_delegate() -> None:
    orchestrator, _, _ = _model(
        '{"action":"delegate","reason":"runtime request",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="requires a current source Agent",
    ):
        orchestrator.decide("web-1 为什么重启？")


def test_direct_action_cannot_silently_switch_current_agent() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"needs triage",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"incident_triage","clarification":null}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="direct cannot change the current Agent",
    ):
        orchestrator.decide(
            "checkout 服务持续 503。",
            source_agent_type="docker_support",
        )


def test_decision_rejects_target_without_requested_capability() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"inspect runtime",'
        '"target_agent_type":"infrastructure_troubleshooter",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="does not expose capability",
    ):
        orchestrator.decide("检查 web-1 是否存在资源配置问题")


def test_decision_rejects_unknown_target_agent() -> None:
    orchestrator, _, _ = _model(
        '{"action":"direct","reason":"unknown specialist",'
        '"target_agent_type":"database_admin",'
        '"capability":"database_debugging","clarification":null}'
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="target Agent is not registered",
    ):
        orchestrator.decide("数据库连接失败")


def test_delegation_decision_respects_existing_trace_loop_protection() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry, max_hops=3)
    context = policy.delegate(
        DelegationContext(original_query="服务持续失败"),
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="initial incident specialist",
    )
    context = policy.delegate(
        context,
        source_agent_type="infrastructure_troubleshooter",
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        reason="inspect container runtime",
    )
    fake = SequenceModel(
        [
            (
                '{"action":"delegate","reason":"return to triage",'
                '"target_agent_type":"infrastructure_troubleshooter",'
                '"capability":"incident_triage","clarification":null}'
            )
        ]
    )
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
        max_hops=3,
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="already appears in delegation trace",
    ):
        orchestrator.decide("容器检查结束，继续分析服务故障", context=context)


def test_context_owner_cannot_be_overridden_by_caller() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)
    context = policy.delegate(
        DelegationContext(original_query="检查服务故障"),
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="initial specialist",
    )
    fake = SequenceModel([])
    orchestrator = OrchestrationDecisionModel(
        registry=registry,
        model=fake,
    )

    with pytest.raises(
        OrchestrationDecisionError,
        match="must match current context owner",
    ):
        orchestrator.decide(
            "继续排查",
            context=context,
            source_agent_type="docker_support",
        )
    assert fake.user_prompts == []


def test_invalid_model_json_is_rejected_before_any_execution() -> None:
    orchestrator, fake, _ = _model("not-json")

    with pytest.raises(
        OrchestrationDecisionError,
        match="invalid JSON",
    ):
        orchestrator.decide("检查 Docker 状态")

    assert len(fake.user_prompts) == 1
