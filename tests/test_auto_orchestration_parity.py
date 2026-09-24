from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    AutoOrchestrationService,
    DelegationExecutionService,
    LangGraphAutoOrchestrationService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
    compare_auto_orchestration_turns,
)
from docker_agent.persistence import init_persistence_store


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
    decision: DummyDecision
    answer: DummyAnswer | None
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


def _engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def _default_docker_turn() -> DummyTurn:
    return DummyTurn(
        decision=DummyDecision(
            route="runtime_tools",
            reason="runtime checked",
        ),
        answer=DummyAnswer("容器运行正常。"),
    )


def _default_infrastructure_turn() -> DummyTurn:
    return DummyTurn(
        decision=DummyDecision(
            route="triage",
            reason="service incident",
        ),
        answer=DummyAnswer(
            "服务仍持续 503，需要继续检查依赖。"
        ),
    )


def _build_service(
    service_type: type[AutoOrchestrationService],
    *,
    decisions: list[str],
    synthesis: list[str] | None = None,
    docker_turn: DummyTurn | None = None,
    infrastructure_turn: DummyTurn | None = None,
) -> tuple[
    AutoOrchestrationService,
    RecordingAgent,
    RecordingAgent,
    SequenceModel,
    SequenceModel,
]:
    engine = _engine()
    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)
    docker = RecordingAgent(
        docker_turn or _default_docker_turn()
    )
    infrastructure = RecordingAgent(
        infrastructure_turn or _default_infrastructure_turn()
    )
    factory.register("docker_support", lambda: docker)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure,
    )

    decision_raw = SequenceModel(decisions)
    synthesis_raw = SequenceModel(
        synthesis
        or [
            (
                '{"answer":"容器层面正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ]
    )

    service = service_type(
        engine=engine,
        decision_model=OrchestrationDecisionModel(
            registry=registry,
            model=decision_raw,
        ),
        execution_service=DelegationExecutionService(
            registry=registry,
            factory=factory,
        ),
        synthesis_service=OrchestratedSynthesisService(
            model=synthesis_raw,
        ),
    )
    return (
        service,
        docker,
        infrastructure,
        decision_raw,
        synthesis_raw,
    )


def _pair(
    *,
    decisions: list[str],
    synthesis: list[str] | None = None,
    docker_turn: DummyTurn | None = None,
    infrastructure_turn: DummyTurn | None = None,
):
    baseline = _build_service(
        AutoOrchestrationService,
        decisions=decisions,
        synthesis=synthesis,
        docker_turn=docker_turn,
        infrastructure_turn=infrastructure_turn,
    )
    candidate = _build_service(
        LangGraphAutoOrchestrationService,
        decisions=decisions,
        synthesis=synthesis,
        docker_turn=docker_turn,
        infrastructure_turn=infrastructure_turn,
    )
    return baseline, candidate


def test_langgraph_auto_direct_matches_phase8_product_contract() -> None:
    decision = (
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )
    baseline, candidate = _pair(decisions=[decision])

    legacy_turn = baseline[0].chat(
        message="web-1 当前运行状态怎么样？"
    )
    graph_turn = candidate[0].chat(
        message="web-1 当前运行状态怎么样？"
    )
    report = compare_auto_orchestration_turns(
        legacy_turn,
        graph_turn,
    )

    assert report.gate_passed is True
    assert report.mismatches == ()
    assert legacy_turn.answer == graph_turn.answer == "容器运行正常。"
    assert baseline[3].calls == candidate[3].calls == 0
    assert baseline[4].calls == candidate[4].calls == 0
    assert len(baseline[1].questions) == len(candidate[1].questions) == 1
    assert baseline[2].questions == candidate[2].questions == []


def test_langgraph_auto_clarify_matches_without_specialist_calls() -> None:
    decision = (
        '{"action":"clarify","reason":"scope is ambiguous",'
        '"target_agent_type":null,"capability":null,'
        '"clarification":"你希望排查容器问题还是服务级故障？"}'
    )
    baseline, candidate = _pair(decisions=[decision])

    legacy_turn = baseline[0].chat(message="系统有问题")
    graph_turn = candidate[0].chat(message="系统有问题")
    report = compare_auto_orchestration_turns(
        legacy_turn,
        graph_turn,
    )

    assert report.gate_passed is True
    assert legacy_turn.clarification == graph_turn.clarification
    assert baseline[1].questions == candidate[1].questions == []
    assert baseline[2].questions == candidate[2].questions == []
    assert baseline[4].calls == candidate[4].calls == 0


def test_langgraph_auto_handoff_and_synthesis_matches_phase8() -> None:
    decisions = [
        (
            '{"action":"direct","reason":"先检查容器",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        (
            '{"action":"delegate","reason":"问题已扩大到服务级",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
    ]
    synthesis = [
        (
            '{"answer":"容器层面正常，但服务级故障仍存在。",'
            '"hypotheses":["依赖异常仍需验证"],'
            '"unresolved_uncertainties":["503 根因尚未确认"]}'
        )
    ]
    baseline, candidate = _pair(
        decisions=decisions,
        synthesis=synthesis,
    )

    legacy_first = baseline[0].chat(
        message="先检查 checkout 容器。"
    )
    graph_first = candidate[0].chat(
        message="先检查 checkout 容器。"
    )
    assert compare_auto_orchestration_turns(
        legacy_first,
        graph_first,
    ).gate_passed

    legacy_second = baseline[0].chat(
        message="容器正常，但 checkout-api 仍持续 503。",
        conversation_id=legacy_first.conversation.id,
    )
    graph_second = candidate[0].chat(
        message="容器正常，但 checkout-api 仍持续 503。",
        conversation_id=graph_first.conversation.id,
    )
    report = compare_auto_orchestration_turns(
        legacy_second,
        graph_second,
    )

    assert report.gate_passed is True
    assert legacy_second.answer == graph_second.answer
    assert legacy_second.answer == (
        "容器层面正常，但服务级故障仍存在。"
    )
    assert baseline[3].calls == candidate[3].calls == 2
    assert baseline[4].calls == candidate[4].calls == 1
    assert len(baseline[1].questions) == len(candidate[1].questions) == 1
    assert len(baseline[2].questions) == len(candidate[2].questions) == 1
    assert "Prior specialist public result" in candidate[2].questions[0]
    assert baseline[3].user_prompts == candidate[3].user_prompts


def test_langgraph_auto_specialist_clarification_matches_phase8() -> None:
    decision = (
        '{"action":"direct","reason":"runtime diagnostics",'
        '"target_agent_type":"docker_support",'
        '"capability":"runtime_diagnostics","clarification":null}'
    )
    docker_turn = DummyTurn(
        decision=DummyDecision(
            route="runtime_tools",
            reason="container identity required",
            clarification="请提供容器名称。",
        ),
        answer=None,
        needs_clarification=True,
    )
    baseline, candidate = _pair(
        decisions=[decision],
        docker_turn=docker_turn,
    )

    legacy_turn = baseline[0].chat(message="检查容器状态")
    graph_turn = candidate[0].chat(message="检查容器状态")
    report = compare_auto_orchestration_turns(
        legacy_turn,
        graph_turn,
    )

    assert report.gate_passed is True
    assert legacy_turn.route == graph_turn.route == (
        "auto_direct_clarify"
    )
    assert legacy_turn.clarification == graph_turn.clarification
    assert baseline[4].calls == candidate[4].calls == 0


def test_parity_report_surfaces_structural_mismatch() -> None:
    baseline, _ = _pair(
        decisions=[
            (
                '{"action":"direct","reason":"runtime",'
                '"target_agent_type":"docker_support",'
                '"capability":"runtime_diagnostics","clarification":null}'
            )
        ]
    )
    _, candidate = _pair(
        decisions=[
            (
                '{"action":"clarify","reason":"ambiguous",'
                '"target_agent_type":null,"capability":null,'
                '"clarification":"请补充范围。"}'
            )
        ]
    )

    legacy_turn = baseline[0].chat(message="检查系统")
    graph_turn = candidate[0].chat(message="检查系统")
    report = compare_auto_orchestration_turns(
        legacy_turn,
        graph_turn,
    )

    assert report.gate_passed is False
    fields = {item.field for item in report.mismatches}
    assert {
        "route",
        "current_agent_type",
        "needs_clarification",
        "answer_present",
        "clarification_present",
        "trace_stages",
        "trace_agents",
        "specialist_agents",
    } <= fields
