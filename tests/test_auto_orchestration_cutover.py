from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationExecutionService,
    LangGraphProductAutoOrchestrationService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
)
from docker_agent.persistence import (
    init_persistence_store,
    load_conversation,
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
    decision: DummyDecision
    answer: DummyAnswer | None
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


def _runtime(
    *,
    decisions: list[str],
    synthesis: list[str] | None = None,
):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)

    registry = build_agent_registry()
    factory = AgentFactory(registry=registry)
    docker = RecordingAgent(
        DummyTurn(
            decision=DummyDecision(
                route="runtime_tools",
                reason="runtime checked",
            ),
            answer=DummyAnswer("容器运行正常。"),
        )
    )
    infrastructure = RecordingAgent(
        DummyTurn(
            decision=DummyDecision(
                route="triage",
                reason="service incident",
            ),
            answer=DummyAnswer(
                "服务持续 503，需要继续检查依赖。"
            ),
        )
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
                '{"answer":"容器正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ]
    )
    saver = InMemorySaver()

    def build_service() -> LangGraphProductAutoOrchestrationService:
        return LangGraphProductAutoOrchestrationService(
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
            checkpointer_context_factory=lambda: nullcontext(saver),
        )

    return (
        build_service,
        engine,
        docker,
        infrastructure,
        decision_raw,
        synthesis_raw,
    )


def test_product_direct_fast_path_completes_without_pending_approval() -> None:
    build_service, engine, docker, infrastructure, decision, synthesis = (
        _runtime(
            decisions=[
                (
                    '{"action":"direct","reason":"runtime diagnostics",'
                    '"target_agent_type":"docker_support",'
                    '"capability":"runtime_diagnostics",'
                    '"clarification":null}'
                )
            ]
        )
    )
    service = build_service()

    turn = service.chat(message="检查 web-1 当前状态。")

    assert turn.route == "auto_direct"
    assert turn.answer == "容器运行正常。"
    assert turn.approval_status == "not_required"
    assert turn.needs_approval is False
    assert [item.stage for item in turn.trace] == [
        "decision",
        "specialist",
    ]
    assert decision.calls == 0
    assert synthesis.calls == 0
    assert docker.questions == ["检查 web-1 当前状态。"]
    assert infrastructure.questions == []

    snapshot = load_conversation(engine, turn.conversation.id)
    assert [item.role for item in snapshot.messages] == [
        "user",
        "assistant",
    ]


def test_product_delegate_pauses_then_approves_without_duplicate_work() -> None:
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
    build_service, engine, docker, infrastructure, decision, synthesis = (
        _runtime(decisions=decisions)
    )
    service = build_service()

    first = service.chat(message="先检查 checkout 容器。")
    pending = service.chat(
        message="容器正常，但 checkout-api 仍持续 503。",
        conversation_id=first.conversation.id,
    )

    assert pending.route == "auto_approval_pending"
    assert pending.approval_status == "pending"
    assert pending.needs_approval is True
    assert pending.approval_request is not None
    assert pending.approval_request.question == (
        "容器正常，但 checkout-api 仍持续 503。"
    )
    assert pending.approval_request.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert len(docker.questions) == 1
    assert infrastructure.questions == []
    assert decision.calls == 2
    assert synthesis.calls == 0

    paused_snapshot = load_conversation(
        engine,
        first.conversation.id,
    )
    assert [item.role for item in paused_snapshot.messages] == [
        "user",
        "assistant",
        "user",
    ]

    recovered = build_service().pending_approval(
        conversation_id=first.conversation.id,
    )
    assert recovered is not None
    assert recovered.needs_approval is True
    assert recovered.approval_request is not None
    assert (
        recovered.approval_request.interrupt_id
        == pending.approval_request.interrupt_id
    )

    completed = build_service().resume_approval(
        conversation_id=first.conversation.id,
        approved=True,
        comment="允许继续排查。",
    )

    assert completed.route == "auto_synthesis"
    assert completed.approval_status == "approved"
    assert completed.needs_approval is False
    assert completed.answer == "容器正常，但服务级故障仍存在。"
    assert [item.stage for item in completed.trace] == [
        "decision",
        "approval",
        "handoff",
        "specialist",
        "synthesis",
    ]
    assert decision.calls == 2
    assert synthesis.calls == 1
    assert len(docker.questions) == 1
    assert len(infrastructure.questions) == 1

    completed_snapshot = load_conversation(
        engine,
        first.conversation.id,
    )
    assert [item.role for item in completed_snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_product_denied_approval_persists_stop_message_only() -> None:
    decisions = [
        (
            '{"action":"direct","reason":"先检查容器",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        (
            '{"action":"delegate","reason":"需要服务级排查",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
    ]
    build_service, engine, docker, infrastructure, decision, synthesis = (
        _runtime(decisions=decisions)
    )
    service = build_service()
    first = service.chat(message="检查 checkout 容器。")
    service.chat(
        message="继续检查服务级故障。",
        conversation_id=first.conversation.id,
    )

    denied = build_service().resume_approval(
        conversation_id=first.conversation.id,
        approved=False,
        comment="先不要继续。",
    )

    assert denied.route == "auto_approval_denied"
    assert denied.approval_status == "denied"
    assert denied.answer == "操作未获批准，工作流已停止执行。"
    assert decision.calls == 2
    assert synthesis.calls == 0
    assert len(docker.questions) == 1
    assert infrastructure.questions == []

    snapshot = load_conversation(engine, first.conversation.id)
    assert [item.role for item in snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert snapshot.messages[-1].route == "auto_approval_denied"


def test_product_pending_approval_blocks_new_user_message() -> None:
    decisions = [
        (
            '{"action":"direct","reason":"先检查容器",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        (
            '{"action":"delegate","reason":"需要服务级排查",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
    ]
    build_service, _, _, _, decision, _ = _runtime(
        decisions=decisions
    )
    service = build_service()
    first = service.chat(message="检查 checkout 容器。")
    service.chat(
        message="继续检查服务级故障。",
        conversation_id=first.conversation.id,
    )

    with pytest.raises(
        ValueError,
        match="waiting for approval",
    ):
        service.chat(
            message="再发一条消息",
            conversation_id=first.conversation.id,
        )

    assert decision.calls == 2


def test_product_pending_approval_returns_none_after_resolution() -> None:
    decisions = [
        (
            '{"action":"direct","reason":"先检查容器",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        (
            '{"action":"delegate","reason":"需要服务级排查",'
            '"target_agent_type":"infrastructure_troubleshooter",'
            '"capability":"incident_triage","clarification":null}'
        ),
    ]
    build_service, _, _, _, _, _ = _runtime(
        decisions=decisions
    )
    service = build_service()
    first = service.chat(message="检查 checkout 容器。")
    service.chat(
        message="继续检查服务级故障。",
        conversation_id=first.conversation.id,
    )
    service.resume_approval(
        conversation_id=first.conversation.id,
        approved=False,
    )

    assert (
        build_service().pending_approval(
            conversation_id=first.conversation.id,
        )
        is None
    )
