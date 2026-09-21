from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.api.chat import ChatSessionManager
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan
from docker_agent.persistence import (
    ChatConversationMismatch,
    ConversationAgentTypeMismatch,
    PersistentChatCoordinator,
    create_conversation,
    init_persistence_store,
    list_agent_runs,
    list_conversations,
    load_conversation,
)


class FakeLangGraphAgent:
    def handle(self, question: str) -> LangGraphAgentTurnResult:
        if "User clarification:" not in question:
            return LangGraphAgentTurnResult(
                decision=AgentRouteDecision(
                    route="clarify",
                    reason="missing container",
                    container_ref=None,
                    tools=(),
                    clarification="请提供容器名称。",
                    use_docs=False,
                ),
                answer=None,
                runtime_trace=(),
                supervisor_plan=SupervisorPlan(
                    workers=(),
                    reason="missing container",
                    clarification="请提供容器名称。",
                ),
                worker_trace=(),
            )

        return LangGraphAgentTurnResult(
            decision=AgentRouteDecision(
                route="runtime_tools",
                reason="container supplied",
                container_ref="web",
                tools=("docker_stats",),
                clarification=None,
                use_docs=False,
            ),
            answer=_answer("web 当前使用 128MiB 内存。[R1]"),
            runtime_trace=(),
            supervisor_plan=SupervisorPlan(
                workers=("runtime", "diagnosis"),
                reason="container supplied",
            ),
            worker_trace=(
                WorkerExecutionRecord(
                    index=1,
                    role="runtime",
                    tool_results_added=1,
                    evidence_added=1,
                    runtime_steps_added=2,
                    answer_created=False,
                ),
                WorkerExecutionRecord(
                    index=2,
                    role="diagnosis",
                    tool_results_added=0,
                    evidence_added=0,
                    runtime_steps_added=0,
                    answer_created=True,
                ),
            ),
        )


class FailingAgent:
    def handle(self, question: str) -> LangGraphAgentTurnResult:
        raise RuntimeError("model failed api_key=super-secret")


class ImmediateAnswerAgent:
    def handle(self, question: str) -> LangGraphAgentTurnResult:
        return LangGraphAgentTurnResult(
            decision=AgentRouteDecision(
                route="docs_only",
                reason="docs are enough",
                container_ref=None,
                tools=(),
                clarification=None,
                use_docs=True,
            ),
            answer=_answer(f"收到：{question} [1]"),
            runtime_trace=(),
            supervisor_plan=SupervisorPlan(
                workers=("knowledge", "diagnosis"),
                reason="docs are enough",
            ),
            worker_trace=(
                WorkerExecutionRecord(
                    index=1,
                    role="knowledge",
                    tool_results_added=0,
                    evidence_added=1,
                    runtime_steps_added=0,
                    answer_created=False,
                ),
                WorkerExecutionRecord(
                    index=2,
                    role="diagnosis",
                    tool_results_added=0,
                    evidence_added=0,
                    runtime_steps_added=0,
                    answer_created=True,
                ),
            ),
        )


def _answer(text: str) -> AgentAnswer:
    return AgentAnswer(
        answer=text,
        doc_sources=(),
        cited_doc_sources=(),
        doc_citation_indices=(),
        runtime_sources=(),
        cited_runtime_sources=(),
        runtime_citation_indices=(),
        docs_context_truncated=False,
        runtime_context_truncated=False,
    )


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def test_persistent_chat_keeps_conversation_id_across_clarification() -> None:
    engine = _engine()
    sessions = ChatSessionManager(agent_factory=FakeLangGraphAgent)
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=sessions,
    )

    first = coordinator.chat(message="我的容器用了多少内存？")

    assert first.session_active is True
    assert first.conversation.agent_type == "docker_support"
    assert first.conversation.title == "我的容器用了多少内存？"

    second = coordinator.chat(
        message="web",
        conversation_id=first.conversation.id,
        session_id=first.session_id,
    )

    assert second.conversation.id == first.conversation.id
    assert second.session_id == first.session_id
    assert second.session_active is False
    assert second.result.answer is not None
    assert second.result.answer.answer == "web 当前使用 128MiB 内存。[R1]"

    snapshot = load_conversation(engine, first.conversation.id)
    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message.content for message in snapshot.messages] == [
        "我的容器用了多少内存？",
        "请提供容器名称。",
        "web",
        "web 当前使用 128MiB 内存。[R1]",
    ]
    assert len(snapshot.executions) == 2

    runs = list_agent_runs(
        engine,
        conversation_id=first.conversation.id,
    )
    assert len(runs) == 2
    assert {run.status for run in runs} == {"succeeded"}
    assert {run.route for run in runs} == {
        "clarify",
        "runtime_tools",
    }


def test_existing_conversation_can_receive_independent_completed_turn() -> None:
    engine = _engine()
    sessions = ChatSessionManager(agent_factory=ImmediateAnswerAgent)
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=sessions,
    )

    first = coordinator.chat(message="Docker volume 是什么？")
    second = coordinator.chat(
        message="那 bind mount 呢？",
        conversation_id=first.conversation.id,
    )

    assert first.session_active is False
    assert second.session_active is False
    assert second.conversation.id == first.conversation.id
    assert second.session_id != first.session_id

    snapshot = load_conversation(engine, first.conversation.id)
    assert len(snapshot.messages) == 4
    assert len(snapshot.executions) == 2


def test_continuing_session_requires_durable_conversation_id() -> None:
    engine = _engine()
    sessions = ChatSessionManager(agent_factory=FakeLangGraphAgent)
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=sessions,
    )

    first = coordinator.chat(message="我的容器用了多少内存？")

    try:
        coordinator.chat(
            message="web",
            session_id=first.session_id,
        )
    except ValueError as exc:
        assert str(exc) == (
            "conversation_id is required when continuing a session"
        )
    else:
        raise AssertionError("ValueError was not raised")


def test_active_session_cannot_be_reused_for_another_conversation() -> None:
    engine = _engine()
    sessions = ChatSessionManager(agent_factory=FakeLangGraphAgent)
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=sessions,
    )

    first = coordinator.chat(message="我的容器用了多少内存？")
    other = create_conversation(
        engine,
        conversation_id="conversation-other",
    )

    try:
        coordinator.chat(
            message="web",
            conversation_id=other.id,
            session_id=first.session_id,
        )
    except ChatConversationMismatch as exc:
        assert str(exc) == "session_id belongs to another conversation"
    else:
        raise AssertionError("ChatConversationMismatch was not raised")


def test_conversation_agent_type_must_match_coordinator() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        agent_type="future_agent",
        conversation_id="conversation-future",
    )
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(agent_factory=ImmediateAnswerAgent),
    )

    try:
        coordinator.chat(
            message="hello",
            conversation_id=conversation.id,
        )
    except ConversationAgentTypeMismatch as exc:
        assert "future_agent" in str(exc)
        assert "docker_support" in str(exc)
    else:
        raise AssertionError("ConversationAgentTypeMismatch was not raised")


def test_persistent_chat_records_failed_run_and_reraises_original_error() -> None:
    engine = _engine()
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(agent_factory=FailingAgent),
    )

    try:
        coordinator.chat(message="触发一次失败")
    except RuntimeError as exc:
        assert str(exc) == "model failed api_key=super-secret"
    else:
        raise AssertionError("RuntimeError was not raised")

    conversations = list_conversations(engine)
    assert len(conversations) == 1

    runs = list_agent_runs(
        engine,
        conversation_id=conversations[0].id,
    )
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "failed"
    assert run.error_type == "RuntimeError"
    assert run.error_message is not None
    assert "super-secret" not in run.error_message
    assert "[REDACTED]" in run.error_message
    assert run.completed_at is not None



def _telemetry_database_error() -> OperationalError:
    return OperationalError(
        "UPDATE agent_runs",
        {},
        RuntimeError("telemetry database unavailable"),
    )


def test_failed_turn_keeps_original_error_when_telemetry_finalize_fails(
    monkeypatch,
) -> None:
    engine = _engine()
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(agent_factory=FailingAgent),
    )

    def fail_telemetry(*args, **kwargs):
        raise _telemetry_database_error()

    monkeypatch.setattr(
        "docker_agent.persistence.chat.finalize_agent_run_failure",
        fail_telemetry,
    )

    try:
        coordinator.chat(message="触发失败")
    except RuntimeError as exc:
        assert str(exc) == "model failed api_key=super-secret"
    else:
        raise AssertionError("original RuntimeError was not raised")


def test_successful_turn_survives_telemetry_finalize_failure(
    monkeypatch,
) -> None:
    engine = _engine()
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(agent_factory=ImmediateAnswerAgent),
    )

    def fail_telemetry(*args, **kwargs):
        raise _telemetry_database_error()

    monkeypatch.setattr(
        "docker_agent.persistence.chat.finalize_agent_run_success",
        fail_telemetry,
    )

    turn = coordinator.chat(message="Docker volume 是什么？")

    assert turn.result.answer is not None
    assert turn.result.answer.answer == "收到：Docker volume 是什么？ [1]"
    snapshot = load_conversation(engine, turn.conversation.id)
    assert len(snapshot.messages) == 2
    assert len(snapshot.executions) == 1
