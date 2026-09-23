from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from docker_agent.main import app
from docker_agent.orchestration import (
    AutoOrchestrationTurn,
    AutoTraceStep,
    SpecialistResultEnvelope,
)
from docker_agent.persistence import ConversationNotFound
from docker_agent.persistence.store import ConversationRecord


class FakeAutoService:
    def __init__(self, turn: AutoOrchestrationTurn | None = None) -> None:
        self.turn = turn
        self.calls: list[tuple[str, str | None]] = []

    def chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
    ) -> AutoOrchestrationTurn:
        self.calls.append((message, conversation_id))
        if self.turn is None:
            raise ConversationNotFound(conversation_id or "missing")
        return self.turn


def _turn() -> AutoOrchestrationTurn:
    conversation = ConversationRecord(
        id="auto-conversation",
        agent_type="auto_orchestration",
        title="检查 checkout 服务",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        updated_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    specialist = SpecialistResultEnvelope(
        agent_type="infrastructure_troubleshooter",
        route="triage",
        reason="service incident",
        needs_clarification=False,
        clarification=None,
        summary="checkout-api 持续 503。",
    )
    return AutoOrchestrationTurn(
        conversation=conversation,
        answer="当前仍是服务级故障，建议继续检查依赖健康度。",
        clarification=None,
        current_agent_type="infrastructure_troubleshooter",
        route="auto_synthesis",
        trace=(
            AutoTraceStep(
                stage="decision",
                label="智能判断",
                agent_type="infrastructure_troubleshooter",
                capability="incident_triage",
                reason="需要服务级排障",
            ),
            AutoTraceStep(
                stage="specialist",
                label="专家处理",
                agent_type="infrastructure_troubleshooter",
                capability="incident_triage",
                reason="需要服务级排障",
            ),
        ),
        specialist_results=(specialist,),
        synthesized=True,
    )


def test_auto_chat_endpoint_returns_trace_and_owner(monkeypatch) -> None:
    service = FakeAutoService(_turn())
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/auto",
        json={
            "message": "继续排查 checkout-api",
            "conversation_id": "auto-conversation",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Conversation-ID"] == "auto-conversation"
    assert response.headers["X-Agent-Type"] == "auto_orchestration"
    assert response.headers["X-Orchestration-Owner"] == (
        "infrastructure_troubleshooter"
    )
    payload = response.json()
    assert payload["mode"] == "auto"
    assert payload["current_agent_type"] == (
        "infrastructure_troubleshooter"
    )
    assert payload["synthesized"] is True
    assert payload["trace"][0]["label"] == "智能判断"
    assert payload["specialist_results"][0]["agent_type"] == (
        "infrastructure_troubleshooter"
    )
    assert service.calls == [
        ("继续排查 checkout-api", "auto-conversation")
    ]


def test_auto_chat_endpoint_maps_missing_conversation_to_404(
    monkeypatch,
) -> None:
    service = FakeAutoService()
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/auto",
        json={
            "message": "继续",
            "conversation_id": "missing",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation was not found."
