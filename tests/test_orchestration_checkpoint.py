from __future__ import annotations

from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import docker_agent.orchestration.checkpoint as checkpoint_module
from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    DelegationContext,
    DelegationExecutionService,
    OrchestratedSynthesisService,
    OrchestrationDecisionModel,
    SpecialistResultEnvelope,
)
from docker_agent.orchestration.checkpoint import (
    CHECKPOINT_NAMESPACE,
    open_postgres_orchestration_checkpointer,
    orchestration_checkpoint_serializer,
    orchestration_thread_config,
    postgres_checkpoint_uri,
)
from docker_agent.orchestration.envelope import (
    SpecialistDocSource,
    SpecialistRuntimeSource,
)
from docker_agent.orchestration.checkpoint_graph import (
    build_checkpointed_orchestration_graph,
    read_checkpointed_orchestration,
    resume_checkpointed_orchestration,
    start_checkpointed_orchestration,
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
        _turn(
            "容器运行正常。",
            route="runtime_tools",
            reason="runtime inspected",
        )
    )
    infrastructure = RecordingAgent(
        _turn(
            "服务仍持续 503，需要继续检查依赖。",
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

    return (
        OrchestrationDecisionModel(
            registry=registry,
            model=decision_raw,
            max_hops=2,
        ),
        DelegationExecutionService(
            registry=registry,
            factory=factory,
            max_hops=2,
        ),
        OrchestratedSynthesisService(
            model=synthesis_raw,
        ),
        decision_raw,
        synthesis_raw,
        docker,
        infrastructure,
    )


def test_checkpoint_graph_pauses_before_synthesis_and_resumes_without_rework() -> None:
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
                '{"answer":"容器正常，但服务级故障仍存在。",'
                '"hypotheses":["依赖异常仍需验证"],'
                '"unresolved_uncertainties":["503 根因尚未确认"]}'
            )
        ],
    )
    saver = InMemorySaver()
    graph = build_checkpointed_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )

    paused = start_checkpointed_orchestration(
        graph,
        thread_id="checkout-incident-1",
        question="容器正常，但 checkout-api 仍持续 503。",
        context=DelegationContext(
            original_query="checkout 服务持续失败"
        ),
        source_agent_type="docker_support",
        user_observations=("checkout-api 持续 503。",),
        prior_specialist_result=prior,
        interrupt_before=("synthesis",),
    )

    assert paused.completed is False
    assert paused.next_nodes == ("synthesis",)
    assert paused.answer is None
    assert paused.clarification is None
    assert paused.synthesis is None
    assert paused.current_specialist_result is not None
    assert paused.current_specialist_result.agent_type == (
        "infrastructure_troubleshooter"
    )
    assert paused.trace == (
        "decision",
        "delegate",
        "specialist",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == []
    assert len(infrastructure.questions) == 1

    resumed = resume_checkpointed_orchestration(
        graph,
        thread_id="checkout-incident-1",
    )

    assert resumed.completed is True
    assert resumed.next_nodes == ()
    assert resumed.answer == "容器正常，但服务级故障仍存在。"
    assert resumed.clarification is None
    assert resumed.synthesis is not None
    assert resumed.trace == (
        "decision",
        "delegate",
        "specialist",
        "synthesis",
    )
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 1
    assert docker.questions == []
    assert len(infrastructure.questions) == 1


def test_checkpoint_graph_can_resume_from_new_compiled_graph_with_same_saver() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        decision_raw,
        synthesis_raw,
        _,
        infrastructure,
    ) = _runtime(
        decision_response=(
            '{"action":"delegate","reason":"service failure remains",'
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
    saver = InMemorySaver()
    graph1 = build_checkpointed_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
    )
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
    )

    start_checkpointed_orchestration(
        graph1,
        thread_id="resume-across-graph-instance",
        question="继续排查 503。",
        context=DelegationContext(
            original_query="服务持续失败"
        ),
        source_agent_type="docker_support",
        prior_specialist_result=prior,
        interrupt_before=("synthesis",),
    )

    graph2 = build_checkpointed_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
    )
    restored = read_checkpointed_orchestration(
        graph2,
        thread_id="resume-across-graph-instance",
    )
    assert restored.completed is False
    assert restored.next_nodes == ("synthesis",)

    resumed = resume_checkpointed_orchestration(
        graph2,
        thread_id="resume-across-graph-instance",
    )
    assert resumed.completed is True
    assert resumed.answer == "综合完成。"
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 1
    assert len(infrastructure.questions) == 1


def test_checkpoint_state_persists_public_result_not_raw_execution() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        _,
        _,
        _,
        _,
    ) = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
    )
    saver = InMemorySaver()
    graph = build_checkpointed_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
    )

    result = start_checkpointed_orchestration(
        graph,
        thread_id="public-state-only",
        question="检查 web-1",
    )

    assert result.completed is True
    snapshot = graph.get_state(
        orchestration_thread_config("public-state-only")
    )
    assert "execution" not in snapshot.values
    assert "turn" not in snapshot.values
    assert isinstance(
        snapshot.values["current_specialist_result"],
        SpecialistResultEnvelope,
    )


def test_checkpoint_graph_complete_thread_cannot_resume_or_restart() -> None:
    (
        decision_model,
        execution_service,
        synthesis_service,
        decision_raw,
        synthesis_raw,
        docker,
        _,
    ) = _runtime(
        decision_response=(
            '{"action":"direct","reason":"runtime diagnostics",'
            '"target_agent_type":"docker_support",'
            '"capability":"runtime_diagnostics","clarification":null}'
        ),
        synthesis_responses=[],
    )
    saver = InMemorySaver()
    graph = build_checkpointed_orchestration_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
        checkpointer=saver,
    )

    completed = start_checkpointed_orchestration(
        graph,
        thread_id="completed-thread",
        question="检查 web-1",
    )
    assert completed.completed is True
    assert completed.answer == "容器运行正常。"
    assert decision_raw.calls == 1
    assert synthesis_raw.calls == 0
    assert docker.questions == ["检查 web-1"]

    with pytest.raises(
        ValueError,
        match="no pending orchestration work",
    ):
        resume_checkpointed_orchestration(
            graph,
            thread_id="completed-thread",
        )

    with pytest.raises(
        ValueError,
        match="already contains orchestration state",
    ):
        start_checkpointed_orchestration(
            graph,
            thread_id="completed-thread",
            question="再次运行",
        )


def test_checkpoint_helpers_validate_thread_and_postgres_uri() -> None:
    assert orchestration_thread_config("abc") == {
        "configurable": {
            "thread_id": "abc",
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }

    with pytest.raises(
        ValueError,
        match="thread_id must not be empty",
    ):
        orchestration_thread_config("   ")

    uri = postgres_checkpoint_uri(
        "postgresql+psycopg://user:secret@localhost:5432/docker_agent"
    )
    assert uri == (
        "postgresql://user:secret@localhost:5432/docker_agent"
    )

    with pytest.raises(
        ValueError,
        match="require PostgreSQL",
    ):
        postgres_checkpoint_uri("sqlite+pysqlite:///:memory:")


def test_checkpoint_serializer_round_trips_allowlisted_public_types() -> None:
    serializer = orchestration_checkpoint_serializer()
    value = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="runtime inspected",
        needs_clarification=False,
        clarification=None,
        summary="容器运行正常。",
        doc_sources=(
            SpecialistDocSource(
                index=1,
                title="Docker docs",
                section="Run containers",
                source_url="https://docs.docker.com/example/",
            ),
        ),
        runtime_sources=(
            SpecialistRuntimeSource(
                index=1,
                tool="docker_ps",
                command=("docker", "ps"),
                ok=True,
            ),
        ),
    )

    encoded = serializer.dumps_typed(value)
    decoded = serializer.loads_typed(encoded)

    assert decoded == value


def test_postgres_checkpointer_uses_safe_connection_and_explicit_setup(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyConnection:
        def close(self) -> None:
            captured["closed"] = True

    class DummySaver:
        def __init__(self, connection, *, serde) -> None:
            captured["connection"] = connection
            captured["serde"] = serde
            captured["saver"] = self

        def setup(self) -> None:
            captured["setup_called"] = True

    connection = DummyConnection()

    def fake_connect(uri, *, autocommit, row_factory):
        captured["uri"] = uri
        captured["autocommit"] = autocommit
        captured["row_factory"] = row_factory
        return connection

    monkeypatch.setattr(
        checkpoint_module.psycopg,
        "connect",
        fake_connect,
    )
    monkeypatch.setattr(
        checkpoint_module,
        "PostgresSaver",
        DummySaver,
    )

    with open_postgres_orchestration_checkpointer(
        database_url=(
            "postgresql+psycopg://user:secret@localhost:5432/docker_agent"
        ),
        setup=True,
    ) as saver:
        assert saver is captured["saver"]
        assert "closed" not in captured

    assert captured["uri"] == (
        "postgresql://user:secret@localhost:5432/docker_agent"
    )
    assert captured["autocommit"] is True
    assert captured["row_factory"] is checkpoint_module.dict_row
    assert captured["setup_called"] is True
    assert captured["closed"] is True
