from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.evidence import RuntimeEvidenceSource
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.api.chat import ChatSessionManager
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.main import app
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan
from docker_agent.persistence import (
    PersistentChatCoordinator,
    init_persistence_store,
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
                    clarification="请提供容器名称或 ID。",
                    use_docs=False,
                ),
                answer=None,
                runtime_trace=(),
                supervisor_plan=SupervisorPlan(
                    workers=(),
                    reason="missing container",
                    clarification="请提供容器名称或 ID。",
                ),
                worker_trace=(),
            )

        runtime_source = RuntimeEvidenceSource(
            index=1,
            tool="docker_logs",
            command=("docker", "logs", "--tail", "100", "web"),
            ok=True,
        )
        answer = AgentAnswer(
            answer="web 的日志显示启动失败。[R1]",
            doc_sources=(),
            cited_doc_sources=(),
            doc_citation_indices=(),
            runtime_sources=(runtime_source,),
            cited_runtime_sources=(runtime_source,),
            runtime_citation_indices=(1,),
            docs_context_truncated=False,
            runtime_context_truncated=False,
        )
        return LangGraphAgentTurnResult(
            decision=AgentRouteDecision(
                route="runtime_tools",
                reason="container supplied",
                container_ref="web",
                tools=("docker_logs",),
                clarification=None,
                use_docs=False,
            ),
            answer=answer,
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


def _coordinator() -> tuple[PersistentChatCoordinator, Engine]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(agent_factory=FakeLangGraphAgent),
    )
    return coordinator, engine


def test_chat_endpoint_persists_durable_conversation_across_clarification(
    monkeypatch,
) -> None:
    coordinator, engine = _coordinator()
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda: coordinator,
    )
    client = TestClient(app)

    first = client.post(
        "/chat",
        json={"message": "我的容器为什么一直重启？"},
        headers={"X-Request-ID": "chat-request-1"},
    )

    assert first.status_code == 200
    assert first.headers["X-Request-ID"] == "chat-request-1"
    first_payload = first.json()
    conversation_id = first_payload["conversation_id"]
    session_id = first_payload["session_id"]
    assert conversation_id
    assert session_id
    assert first.headers["X-Conversation-ID"] == conversation_id
    assert first.headers["X-Run-ID"]
    assert first_payload["route"] == "clarify"
    assert first_payload["session_active"] is True
    assert first_payload["clarification"] == "请提供容器名称或 ID。"
    assert first_payload["execution"]["planned_workers"] == []

    second = client.post(
        "/chat",
        json={
            "message": "web",
            "conversation_id": conversation_id,
            "session_id": session_id,
        },
    )

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["conversation_id"] == conversation_id
    assert second_payload["session_id"] == session_id
    assert second_payload["route"] == "runtime_tools"
    assert second_payload["session_active"] is False
    assert second_payload["answer"] == "web 的日志显示启动失败。[R1]"
    assert second_payload["runtime_sources"][0]["tool"] == "docker_logs"
    assert second_payload["execution"]["planned_workers"] == [
        "runtime",
        "diagnosis",
    ]

    snapshot = load_conversation(engine, conversation_id)
    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert len(snapshot.executions) == 2

    expired = client.post(
        "/chat",
        json={
            "message": "再看看",
            "conversation_id": conversation_id,
            "session_id": session_id,
        },
    )
    assert expired.status_code == 404


def test_chat_endpoint_requires_conversation_id_for_session_follow_up(
    monkeypatch,
) -> None:
    coordinator, _engine = _coordinator()
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda: coordinator,
    )
    client = TestClient(app)

    first = client.post("/chat", json={"message": "我的容器怎么了？"})
    session_id = first.json()["session_id"]

    response = client.post(
        "/chat",
        json={
            "message": "web",
            "session_id": session_id,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "conversation_id is required when continuing a session"
    )


def test_delete_chat_session_keeps_persisted_conversation_history(
    monkeypatch,
) -> None:
    coordinator, engine = _coordinator()
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda: coordinator,
    )
    client = TestClient(app)

    first = client.post("/chat", json={"message": "我的容器怎么了？"})
    payload = first.json()

    response = client.delete(f"/chat/{payload['session_id']}")

    assert response.status_code == 204
    assert coordinator.sessions.active_sessions() == 0

    snapshot = load_conversation(engine, payload["conversation_id"])
    assert [message.role for message in snapshot.messages] == [
        "user",
        "assistant",
    ]
    assert snapshot.messages[1].content == "请提供容器名称或 ID。"
