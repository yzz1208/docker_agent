from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.api.chat import ChatSessionManager
from docker_agent.main import app
from docker_agent.persistence import (
    PersistentChatCoordinator,
    append_message,
    create_conversation,
    init_persistence_store,
    save_execution,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def test_list_conversations_returns_product_summaries(monkeypatch) -> None:
    engine = _engine()
    first = create_conversation(
        engine,
        agent_type="docker_support",
        title="First",
        conversation_id="conversation-a",
    )
    second = create_conversation(
        engine,
        agent_type="future_agent",
        title="Second",
        conversation_id="conversation-b",
    )
    append_message(
        engine,
        conversation_id=second.id,
        role="user",
        content="new activity",
    )

    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/conversations")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [
        second.id,
        first.id,
    ]
    assert payload[0]["agent_type"] == "future_agent"
    assert payload[0]["title"] == "Second"


def test_list_conversations_supports_limit_and_offset(monkeypatch) -> None:
    engine = _engine()
    first = create_conversation(
        engine,
        conversation_id="conversation-a",
    )
    second = create_conversation(
        engine,
        conversation_id="conversation-b",
    )
    append_message(
        engine,
        conversation_id=first.id,
        role="user",
        content="make first newest",
    )

    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/conversations?limit=1&offset=1")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == second.id


def test_get_conversation_attaches_execution_to_assistant_message(
    monkeypatch,
) -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        title="Memory check",
        conversation_id="conversation-memory",
    )
    user = append_message(
        engine,
        conversation_id=conversation.id,
        role="user",
        content="web 现在用了多少内存？",
        message_id="message-user",
    )
    assistant = append_message(
        engine,
        conversation_id=conversation.id,
        role="assistant",
        content="web 当前使用 128MiB 内存。[R1]",
        route="runtime_tools",
        use_docs=False,
        message_id="message-assistant",
    )
    save_execution(
        engine,
        message_id=assistant.id,
        planned_workers=("runtime", "diagnosis"),
        completed_workers=("runtime", "diagnosis"),
        worker_trace=(
            {
                "index": 1,
                "role": "runtime",
                "tool_results_added": 1,
                "evidence_added": 1,
                "runtime_steps_added": 2,
                "answer_created": False,
            },
            {
                "index": 2,
                "role": "diagnosis",
                "tool_results_added": 0,
                "evidence_added": 0,
                "runtime_steps_added": 0,
                "answer_created": True,
            },
        ),
    )

    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(f"/conversations/{conversation.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation"]["id"] == conversation.id
    assert payload["conversation"]["title"] == "Memory check"
    assert [item["id"] for item in payload["messages"]] == [
        user.id,
        assistant.id,
    ]
    assert payload["messages"][0]["execution"] is None

    execution = payload["messages"][1]["execution"]
    assert execution["planned_workers"] == ["runtime", "diagnosis"]
    assert execution["completed_workers"] == ["runtime", "diagnosis"]
    assert [item["role"] for item in execution["worker_trace"]] == [
        "runtime",
        "diagnosis",
    ]


def test_get_conversation_returns_404_for_unknown_id(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/conversations/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation was not found."


def test_list_conversations_rejects_invalid_pagination(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/conversations?limit=0")

    assert response.status_code == 400
    assert response.json()["detail"] == "limit must be positive"



def test_patch_conversation_renames_sidebar_title(monkeypatch) -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        title="Old",
        conversation_id="conversation-rename-api",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.patch(
        f"/conversations/{conversation.id}",
        json={"title": "  New sidebar title  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == conversation.id
    assert payload["title"] == "New sidebar title"


def test_patch_conversation_returns_404_for_unknown_id(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.patch(
        "/conversations/missing",
        json={"title": "New"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation was not found."


def test_delete_conversation_removes_history(monkeypatch) -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-delete-api",
    )
    append_message(
        engine,
        conversation_id=conversation.id,
        role="user",
        content="hello",
    )
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(
            agent_factory=lambda: object(),  # type: ignore[arg-type]
        ),
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda: coordinator,
    )
    client = TestClient(app)

    response = client.delete(f"/conversations/{conversation.id}")

    assert response.status_code == 204
    detail = client.get(f"/conversations/{conversation.id}")
    assert detail.status_code == 404


def test_delete_conversation_returns_404_for_unknown_id(monkeypatch) -> None:
    engine = _engine()
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(
            agent_factory=lambda: object(),  # type: ignore[arg-type]
        ),
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_chat_coordinator",
        lambda: coordinator,
    )
    client = TestClient(app)

    response = client.delete("/conversations/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation was not found."
