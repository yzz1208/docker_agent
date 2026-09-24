from sqlalchemy import create_engine

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.evidence import RuntimeEvidenceSource
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan
from docker_agent.persistence import (
    create_conversation,
    init_persistence_store,
    load_conversation,
    persist_agent_turn,
    persist_langgraph_turn,
)
from docker_agent.rag.context import CitationSource


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


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


def test_persist_langgraph_turn_saves_messages_and_execution_metadata() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-1",
    )
    result = LangGraphAgentTurnResult(
        decision=AgentRouteDecision(
            route="docs_only",
            reason="docs are sufficient",
            container_ref=None,
            tools=(),
            clarification=None,
            use_docs=True,
        ),
        answer=_answer("Docker volume 由 Docker 管理。[1]"),
        runtime_trace=(),
        supervisor_plan=SupervisorPlan(
            workers=("knowledge", "diagnosis"),
            reason="docs are sufficient",
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

    persisted = persist_langgraph_turn(
        engine,
        conversation_id=conversation.id,
        user_message="Docker volume 是什么？",
        result=result,
    )
    snapshot = load_conversation(engine, conversation.id)

    assert persisted.user_message.role == "user"
    assert persisted.user_message.content == "Docker volume 是什么？"
    assert persisted.assistant_message.role == "assistant"
    assert persisted.assistant_message.content == "Docker volume 由 Docker 管理。[1]"
    assert persisted.assistant_message.route == "docs_only"
    assert persisted.assistant_message.use_docs is True
    assert persisted.assistant_message.clarification is None

    assert persisted.execution.message_id == persisted.assistant_message.id
    assert persisted.execution.planned_workers == ("knowledge", "diagnosis")
    assert persisted.execution.completed_workers == ("knowledge", "diagnosis")
    assert persisted.execution.worker_trace[0]["role"] == "knowledge"
    assert persisted.execution.worker_trace[1]["answer_created"] is True

    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
    ]
    assert snapshot.executions == (persisted.execution,)


def test_persist_agent_turn_saves_safe_cited_source_metadata() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-sources",
    )
    answer = AgentAnswer(
        answer="来自文档。[1] 当前容器可见。[R1]",
        doc_sources=(),
        cited_doc_sources=(
            CitationSource(
                index=1,
                chunk_id="chunk-1",
                title="Docker volumes",
                section_path=("Storage", "Volumes"),
                source_url="https://docs.docker.com/engine/storage/volumes/",
                file_path="volumes.md",
            ),
        ),
        doc_citation_indices=(1,),
        runtime_sources=(),
        cited_runtime_sources=(
            RuntimeEvidenceSource(
                index=1,
                tool="docker_ps",
                command=("docker", "ps"),
                ok=True,
            ),
        ),
        runtime_citation_indices=(1,),
        docs_context_truncated=True,
        runtime_context_truncated=False,
    )
    result = LangGraphAgentTurnResult(
        decision=AgentRouteDecision(
            route="runtime_tools",
            reason="combined evidence",
            container_ref=None,
            tools=("docker_ps",),
            clarification=None,
            use_docs=True,
        ),
        answer=answer,
        runtime_trace=(),
        supervisor_plan=SupervisorPlan(
            workers=("knowledge", "runtime", "diagnosis"),
            reason="combined evidence",
        ),
        worker_trace=(),
    )

    persisted = persist_agent_turn(
        engine,
        conversation_id=conversation.id,
        user_message="检查并解释",
        result=result,
    )

    trace = persisted.execution.worker_trace
    assert any(
        item.get("kind") == "doc_source"
        and item.get("title") == "Docker volumes"
        for item in trace
    )
    assert any(
        item.get("kind") == "runtime_source"
        and item.get("tool") == "docker_ps"
        for item in trace
    )
    assert any(
        item.get("kind") == "answer_context"
        and item.get("docs_context_truncated") is True
        for item in trace
    )


def test_persist_langgraph_turn_saves_clarification_as_assistant_message() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-clarify",
    )
    result = LangGraphAgentTurnResult(
        decision=AgentRouteDecision(
            route="clarify",
            reason="container name is missing",
            container_ref=None,
            tools=(),
            clarification="请提供容器名称。",
            use_docs=False,
        ),
        answer=None,
        runtime_trace=(),
        supervisor_plan=SupervisorPlan(
            workers=(),
            reason="container name is missing",
            clarification="请提供容器名称。",
        ),
        worker_trace=(),
    )

    persisted = persist_langgraph_turn(
        engine,
        conversation_id=conversation.id,
        user_message="我的容器为什么退出了？",
        result=result,
    )
    snapshot = load_conversation(engine, conversation.id)

    assert persisted.assistant_message.content == "请提供容器名称。"
    assert persisted.assistant_message.route == "clarify"
    assert persisted.assistant_message.clarification == "请提供容器名称。"
    assert persisted.execution.planned_workers == ()
    assert persisted.execution.completed_workers == ()
    assert persisted.execution.worker_trace == ()
    assert len(snapshot.messages) == 2
    assert len(snapshot.executions) == 1


def test_persist_agent_turn_rejects_missing_assistant_content() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-invalid",
    )
    result = LangGraphAgentTurnResult(
        decision=AgentRouteDecision(
            route="runtime_tools",
            reason="runtime required",
            container_ref="web",
            tools=("docker_stats",),
            clarification=None,
            use_docs=False,
        ),
        answer=None,
        runtime_trace=(),
        supervisor_plan=SupervisorPlan(
            workers=("runtime", "diagnosis"),
            reason="runtime required",
        ),
        worker_trace=(),
    )

    try:
        persist_agent_turn(
            engine,
            conversation_id=conversation.id,
            user_message="web 现在用了多少内存？",
            result=result,
        )
    except ValueError as exc:
        assert str(exc) == (
            "Agent turn has neither answer nor clarification content"
        )
    else:
        raise AssertionError("ValueError was not raised")

    snapshot = load_conversation(engine, conversation.id)
    assert snapshot.messages == ()
    assert snapshot.executions == ()
