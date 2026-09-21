from fastapi.testclient import TestClient

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.evidence import RuntimeEvidenceSource
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.agent.service import AgentTurnResult
from docker_agent.api.chat import ChatSessionManager
from docker_agent.main import app


class FakeAgent:
    def handle(self, question: str) -> AgentTurnResult:
        if "User clarification:" not in question:
            return AgentTurnResult(
                decision=AgentRouteDecision(
                    route="clarify",
                    reason="missing container",
                    container_ref=None,
                    tools=(),
                    clarification="请提供容器名称或 ID。",
                    use_docs=False,
                ),
                answer=None,
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
        return AgentTurnResult(
            decision=AgentRouteDecision(
                route="runtime_tools",
                reason="container supplied",
                container_ref="web",
                tools=("docker_logs",),
                clarification=None,
                use_docs=False,
            ),
            answer=answer,
        )


def test_chat_endpoint_continues_pending_clarification(monkeypatch) -> None:
    manager = ChatSessionManager(agent_factory=FakeAgent)
    monkeypatch.setattr("docker_agent.main.chat_sessions", manager)
    client = TestClient(app)

    first = client.post("/chat", json={"message": "我的容器为什么一直重启？"})

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["route"] == "clarify"
    assert first_payload["session_active"] is True
    assert first_payload["clarification"] == "请提供容器名称或 ID。"

    second = client.post(
        "/chat",
        json={
            "message": "web",
            "session_id": first_payload["session_id"],
        },
    )

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["route"] == "runtime_tools"
    assert second_payload["session_active"] is False
    assert second_payload["answer"] == "web 的日志显示启动失败。[R1]"
    assert second_payload["runtime_sources"][0]["tool"] == "docker_logs"
    assert second_payload["execution"] is None

    expired = client.post(
        "/chat",
        json={
            "message": "再看看",
            "session_id": first_payload["session_id"],
        },
    )
    assert expired.status_code == 404


def test_delete_chat_session_clears_pending_state(monkeypatch) -> None:
    manager = ChatSessionManager(agent_factory=FakeAgent)
    monkeypatch.setattr("docker_agent.main.chat_sessions", manager)
    client = TestClient(app)

    first = client.post("/chat", json={"message": "我的容器怎么了？"})
    session_id = first.json()["session_id"]

    response = client.delete(f"/chat/{session_id}")

    assert response.status_code == 204
    assert manager.active_sessions() == 0
