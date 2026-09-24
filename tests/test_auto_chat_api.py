from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from docker_agent.main import app
from docker_agent.observability import stage_timer
from docker_agent.orchestration import (
    AutoOrchestrationTurn,
    AutoTraceStep,
    HumanApprovalRequest,
    SpecialistResultEnvelope,
)
from docker_agent.persistence import ConversationNotFound
from docker_agent.persistence.store import ConversationRecord


class FakeAutoService:
    def __init__(
        self,
        turn: AutoOrchestrationTurn | None = None,
        *,
        pending_turn: AutoOrchestrationTurn | None = None,
        approval_turn: AutoOrchestrationTurn | None = None,
    ) -> None:
        self.turn = turn
        self.pending_turn = pending_turn
        self.approval_turn = approval_turn
        self.calls: list[tuple[str, str | None]] = []
        self.pending_calls: list[str] = []
        self.approval_calls: list[tuple[str, bool, str | None]] = []

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

    def pending_approval(
        self,
        *,
        conversation_id: str,
    ) -> AutoOrchestrationTurn | None:
        self.pending_calls.append(conversation_id)
        return self.pending_turn

    def resume_approval(
        self,
        *,
        conversation_id: str,
        approved: bool,
        comment: str | None = None,
    ) -> AutoOrchestrationTurn:
        self.approval_calls.append(
            (conversation_id, approved, comment)
        )
        if self.approval_turn is None:
            raise ConversationNotFound(conversation_id)
        return self.approval_turn


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


def test_auto_chat_stream_emits_real_progress_and_final_result(
    monkeypatch,
) -> None:
    class ProgressAutoService(FakeAutoService):
        def chat(
            self,
            *,
            message: str,
            conversation_id: str | None = None,
        ) -> AutoOrchestrationTurn:
            with stage_timer("orchestration_decision"):
                pass
            with stage_timer("answer"):
                pass
            return super().chat(
                message=message,
                conversation_id=conversation_id,
            )

    service = ProgressAutoService(_turn())
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/auto/stream",
        json={
            "message": "继续排查 checkout-api",
            "conversation_id": "auto-conversation",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/event-stream"
    )
    body = response.text
    assert "event: progress" in body
    assert '"stage":"request","status":"started"' in body
    assert (
        '"stage":"orchestration_decision","status":"started"'
        in body
    )
    assert '"stage":"answer","status":"completed"' in body
    assert "event: result" in body
    assert '"conversation_id":"auto-conversation"' in body
    assert service.calls == [
        ("继续排查 checkout-api", "auto-conversation")
    ]


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



def _pending_turn() -> AutoOrchestrationTurn:
    conversation = ConversationRecord(
        id="auto-conversation",
        agent_type="auto_orchestration",
        title="检查 checkout 服务",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        updated_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    request = HumanApprovalRequest(
        interrupt_id="interrupt-1",
        action="delegate",
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="问题已扩大到服务级",
        question="继续排查 checkout-api 503",
        response_schema={
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "comment": {"type": "string"},
            },
            "required": ["approved"],
            "additionalProperties": False,
        },
    )
    return AutoOrchestrationTurn(
        conversation=conversation,
        answer=None,
        clarification=None,
        current_agent_type="docker_support",
        route="auto_approval_pending",
        trace=(
            AutoTraceStep(
                stage="decision",
                label="智能判断",
                agent_type="infrastructure_troubleshooter",
                capability="incident_triage",
                reason="问题已扩大到服务级",
            ),
            AutoTraceStep(
                stage="approval",
                label="等待批准",
                agent_type="infrastructure_troubleshooter",
                capability="incident_triage",
                reason="跨专家转交需要你的批准。",
            ),
        ),
        specialist_results=(),
        synthesized=False,
        approval_status="pending",
        approval_request=request,
    )


def test_auto_chat_endpoint_exposes_pending_approval_contract(
    monkeypatch,
) -> None:
    service = FakeAutoService(_pending_turn())
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/auto",
        json={"message": "继续排查 checkout-api"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "auto_approval_pending"
    assert payload["needs_approval"] is True
    assert payload["approval_status"] == "pending"
    request = payload["approval_request"]
    assert request["action"] == "delegate"
    assert request["target_agent_type"] == (
        "infrastructure_troubleshooter"
    )
    assert request["capability"] == "incident_triage"
    assert request["response_schema"]["required"] == ["approved"]


def test_auto_chat_pending_approval_can_be_recovered(
    monkeypatch,
) -> None:
    service = FakeAutoService(
        pending_turn=_pending_turn(),
    )
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.get(
        "/chat/auto/auto-conversation/approval"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_approval"] is True
    assert payload["approval_request"]["interrupt_id"] == (
        "interrupt-1"
    )
    assert service.pending_calls == ["auto-conversation"]


def test_auto_chat_pending_approval_returns_null_when_absent(
    monkeypatch,
) -> None:
    service = FakeAutoService()
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.get(
        "/chat/auto/auto-conversation/approval"
    )

    assert response.status_code == 200
    assert response.json() is None


def test_auto_chat_approval_endpoint_resumes_product_turn(
    monkeypatch,
) -> None:
    completed = _turn()
    service = FakeAutoService(
        approval_turn=completed,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_auto_orchestration_service",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/auto/auto-conversation/approval",
        json={
            "approved": True,
            "comment": "允许继续排查。",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == completed.answer
    assert payload["needs_approval"] is False
    assert service.approval_calls == [
        ("auto-conversation", True, "允许继续排查。")
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
