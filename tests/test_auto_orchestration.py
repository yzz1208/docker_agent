from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    AutoOrchestrationError,
    AutoOrchestrationService,
    DelegationExecutionService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
)
from docker_agent.persistence import (
    create_conversation,
    init_persistence_store,
    list_conversations,
    load_conversation,
)


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.user_prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


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


def _service(
    *,
    decisions: list[str],
    synthesis: list[str] | None = None,
) -> tuple[
    AutoOrchestrationService,
    Engine,
    RecordingAgent,
    RecordingAgent,
    SequenceModel,
]:
    engine = _engine()
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
            answer=DummyAnswer("服务仍持续 503，需要继续检查依赖。"),
        )
    )
    factory.register("docker_support", lambda: docker)
    factory.register(
        "infrastructure_troubleshooter",
        lambda: infrastructure,
    )
    decision_model = SequenceModel(decisions)
    synthesis_model = SequenceModel(
        synthesis
        or [
            (
                '{"answer":"容器层面正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ]
    )
    service = AutoOrchestrationService(
        engine=engine,
        decision_model=OrchestrationDecisionModel(
            registry=registry,
            model=decision_model,
        ),
        execution_service=DelegationExecutionService(
            registry=registry,
            factory=factory,
        ),
        synthesis_service=OrchestratedSynthesisService(
            model=synthesis_model,
        ),
    )
    return service, engine, docker, infrastructure, decision_model


def test_auto_chat_first_turn_uses_one_specialist_and_persists_history() -> None:
    service, engine, docker, infrastructure, _ = _service(
        decisions=[
            (
                '{"action":"direct","reason":"需要检查容器运行状态",'
                '"target_agent_type":"docker_support",'
                '"capability":"runtime_diagnostics","clarification":null}'
            )
        ]
    )

    turn = service.chat(message="web-1 当前运行状态怎么样？")

    assert turn.answer == "容器运行正常。"
    assert turn.clarification is None
    assert turn.current_agent_type == "docker_support"
    assert turn.route == "auto_direct"
    assert turn.synthesized is False
    assert [step.stage for step in turn.trace] == [
        "decision",
        "specialist",
    ]
    assert len(docker.questions) == 1
    assert infrastructure.questions == []

    conversations = list_conversations(engine)
    assert len(conversations) == 1
    assert conversations[0].agent_type == "auto_orchestration"
    snapshot = load_conversation(
        engine,
        turn.conversation.id,
    )
    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
    ]
    assert snapshot.messages[1].content == "容器运行正常。"
    assert len(snapshot.executions) == 1


def test_auto_chat_follow_up_can_handoff_and_synthesize() -> None:
    service, engine, docker, infrastructure, _ = _service(
        decisions=[
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
    )

    first = service.chat(message="先检查 checkout 容器。")
    second = service.chat(
        message="容器正常，但 checkout-api 仍持续 503。",
        conversation_id=first.conversation.id,
    )

    assert second.synthesized is True
    assert second.answer == "容器层面正常，但服务级故障仍存在。"
    assert second.current_agent_type == "infrastructure_troubleshooter"
    assert second.route == "auto_synthesis"
    assert [step.stage for step in second.trace] == [
        "decision",
        "handoff",
        "specialist",
        "synthesis",
    ]
    assert len(docker.questions) == 1
    assert len(infrastructure.questions) == 1
    assert "Prior specialist public result" in infrastructure.questions[0]
    assert "容器运行正常。" in infrastructure.questions[0]

    snapshot = load_conversation(
        engine,
        first.conversation.id,
    )
    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert snapshot.messages[-1].route == "auto_synthesis"


def test_auto_chat_clarify_does_not_execute_specialist() -> None:
    service, _engine_value, docker, infrastructure, _ = _service(
        decisions=[
            (
                '{"action":"clarify","reason":"范围不明确",'
                '"target_agent_type":null,"capability":null,'
                '"clarification":"你希望排查容器问题还是服务级故障？"}'
            )
        ]
    )

    turn = service.chat(message="帮我看看系统怎么了")

    assert turn.answer is None
    assert turn.clarification == "你希望排查容器问题还是服务级故障？"
    assert turn.needs_clarification is True
    assert turn.current_agent_type is None
    assert docker.questions == []
    assert infrastructure.questions == []


def test_auto_chat_rejects_manual_agent_conversation() -> None:
    service, engine, _, _, _ = _service(decisions=[])

    manual = create_conversation(
        engine,
        agent_type="docker_support",
        title="manual",
    )

    with pytest.raises(
        AutoOrchestrationError,
        match="not an auto-orchestration conversation",
    ):
        service.chat(
            message="继续",
            conversation_id=manual.id,
        )


def test_auto_chat_recent_context_is_bounded_and_marked_untrusted() -> None:
    service, _engine_value, docker, _, decision_model = _service(
        decisions=[
            (
                '{"action":"direct","reason":"runtime",'
                '"target_agent_type":"docker_support",'
                '"capability":"runtime_diagnostics","clarification":null}'
            ),
            (
                '{"action":"direct","reason":"continue runtime",'
                '"target_agent_type":"docker_support",'
                '"capability":"runtime_diagnostics","clarification":null}'
            ),
        ]
    )

    first = service.chat(message="检查 web-1")
    service.chat(
        message="继续检查",
        conversation_id=first.conversation.id,
    )

    assert len(docker.questions) == 2
    assert "最近对话上下文" in decision_model.user_prompts[1]
    assert "不可信数据" in decision_model.user_prompts[1]
    assert "当前用户消息" in docker.questions[1]
