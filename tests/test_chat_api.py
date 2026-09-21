from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.evidence import RuntimeEvidenceSource
from docker_agent.agent.infrastructure import (
    InfrastructureTroubleshooterAgent,
)
from docker_agent.agent.registry import (
    DOCKER_SUPPORT_DESCRIPTOR,
    AgentDescriptor,
    AgentRegistry,
)
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.api.chat import ChatSessionManager
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.config import Settings
from docker_agent.main import app
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan
from docker_agent.persistence import (
    PersistentChatCoordinator,
    init_persistence_store,
    list_conversations,
    load_conversation,
)


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        return self.responses.pop(0)


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


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def _coordinator(
    *,
    engine: Engine | None = None,
    agent_type: str = "docker_support",
) -> tuple[PersistentChatCoordinator, Engine]:
    resolved_engine = engine or _engine()
    coordinator = PersistentChatCoordinator(
        engine=resolved_engine,
        sessions=ChatSessionManager(
            agent_factory=FakeLangGraphAgent,
            agent_type=agent_type,
        ),
        agent_type=agent_type,
    )
    return coordinator, resolved_engine


def _install_chat_runtime(
    monkeypatch,
    *,
    engine: Engine,
    coordinators: dict[str, PersistentChatCoordinator],
) -> None:
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda agent_type="docker_support": coordinators[agent_type],
    )


def test_chat_endpoint_persists_durable_conversation_across_clarification(
    monkeypatch,
) -> None:
    coordinator, engine = _coordinator()
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={"docker_support": coordinator},
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
    assert first.headers["X-Agent-Type"] == "docker_support"
    assert first.headers["X-Run-ID"]
    assert first_payload["agent_type"] == "docker_support"
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
    coordinator, engine = _coordinator()
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={"docker_support": coordinator},
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
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={"docker_support": coordinator},
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


def test_chat_endpoint_routes_new_and_existing_conversation_by_agent_type(
    monkeypatch,
) -> None:
    engine = _engine()
    docker_coordinator, _ = _coordinator(
        engine=engine,
        agent_type="docker_support",
    )
    future_coordinator, _ = _coordinator(
        engine=engine,
        agent_type="future_agent",
    )
    registry = AgentRegistry(
        (
            DOCKER_SUPPORT_DESCRIPTOR,
            AgentDescriptor(
                agent_type="future_agent",
                display_name="Future Agent",
                description="Test-only future Agent.",
                capabilities=("chat",),
                knowledge_sources=(),
                toolsets=(),
                worker_roles=(),
                configuration_schema=(),
            ),
        )
    )
    monkeypatch.setattr(
        "docker_agent.main.agent_registry",
        registry,
    )
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={
            "docker_support": docker_coordinator,
            "future_agent": future_coordinator,
        },
    )
    client = TestClient(app)

    first = client.post(
        "/chat",
        json={
            "message": "我的服务怎么了？",
            "agent_type": "Future-Agent",
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["agent_type"] == "future_agent"
    assert first.headers["X-Agent-Type"] == "future_agent"
    conversation_id = payload["conversation_id"]
    session_id = payload["session_id"]
    assert conversation_id
    assert session_id
    assert list_conversations(engine)[0].agent_type == "future_agent"

    mismatch = client.post(
        "/chat",
        json={
            "message": "切换 Agent",
            "agent_type": "docker_support",
            "conversation_id": conversation_id,
            "session_id": session_id,
        },
    )

    assert mismatch.status_code == 409
    assert "future_agent" in mismatch.json()["detail"]
    assert "docker_support" in mismatch.json()["detail"]

    follow_up = client.post(
        "/chat",
        json={
            "message": "web",
            "conversation_id": conversation_id,
            "session_id": session_id,
        },
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["agent_type"] == "future_agent"
    assert follow_up.json()["answer"] == "web 的日志显示启动失败。[R1]"


def test_chat_endpoint_rejects_unregistered_agent_without_creating_conversation(
    monkeypatch,
) -> None:
    coordinator, engine = _coordinator()
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={"docker_support": coordinator},
    )
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "message": "hello",
            "agent_type": "missing_agent",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Agent type is not registered."
    )
    assert list_conversations(engine) == ()


def test_delete_chat_session_routes_reset_by_agent_type(
    monkeypatch,
) -> None:
    engine = _engine()
    future_coordinator, _ = _coordinator(
        engine=engine,
        agent_type="future_agent",
    )
    registry = AgentRegistry(
        (
            DOCKER_SUPPORT_DESCRIPTOR,
            AgentDescriptor(
                agent_type="future_agent",
                display_name="Future Agent",
                description="Test-only future Agent.",
                capabilities=("chat",),
                knowledge_sources=(),
                toolsets=(),
                worker_roles=(),
                configuration_schema=(),
            ),
        )
    )
    monkeypatch.setattr(
        "docker_agent.main.agent_registry",
        registry,
    )
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={
            "future_agent": future_coordinator,
        },
    )
    client = TestClient(app)

    first = client.post(
        "/chat",
        json={
            "message": "我的服务怎么了？",
            "agent_type": "future_agent",
        },
    )
    session_id = first.json()["session_id"]

    response = client.delete(
        f"/chat/{session_id}",
        params={"agent_type": "future_agent"},
    )

    assert response.status_code == 204
    assert future_coordinator.sessions.active_sessions() == 0


def test_chat_endpoint_runs_real_infrastructure_agent_contract(
    monkeypatch,
) -> None:
    engine = _engine()
    agent = InfrastructureTroubleshooterAgent(
        settings=Settings(),
        router_model=SequenceModel(
            [
                (
                    '{"route":"triage","reason":"concrete service incident",'
                    '"clarification":null}'
                )
            ]
        ),
        answer_model=SequenceModel(
            [
                (
                    "已知事实：checkout-api 返回 503。"
                    "可能原因：依赖异常。"
                    "下一步：检查依赖健康度。"
                )
            ]
        ),
    )
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(
            agent_factory=lambda: agent,
            agent_type="infrastructure_troubleshooter",
        ),
        agent_type="infrastructure_troubleshooter",
    )
    _install_chat_runtime(
        monkeypatch,
        engine=engine,
        coordinators={
            "infrastructure_troubleshooter": coordinator,
        },
    )
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "message": (
                "checkout-api 从 10:20 开始持续返回 503，"
                "依赖请求超时明显增加。"
            ),
            "agent_type": "infrastructure_troubleshooter",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "infrastructure_troubleshooter"
    assert payload["route"] == "triage"
    assert payload["use_docs"] is False
    assert payload["runtime_sources"] == []
    assert payload["doc_sources"] == []
    assert payload["execution"]["planned_workers"] == [
        "triage",
        "diagnosis",
    ]
    assert payload["execution"]["completed_workers"] == [
        "triage",
        "diagnosis",
    ]

    snapshot = load_conversation(
        engine,
        payload["conversation_id"],
    )
    assert snapshot.conversation.agent_type == (
        "infrastructure_troubleshooter"
    )
    assert snapshot.messages[1].route == "triage"
    assert snapshot.executions[0].planned_workers == (
        "triage",
        "diagnosis",
    )
