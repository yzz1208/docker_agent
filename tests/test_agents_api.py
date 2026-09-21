from fastapi.testclient import TestClient

from docker_agent.main import app


def test_agents_api_lists_runtime_supported_agents() -> None:
    client = TestClient(app)

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json() == [
        {
            "agent_type": "docker_support",
            "display_name": "Docker Support",
            "description": (
                "Docker technical support Agent with documentation "
                "retrieval, read-only runtime diagnostics, and "
                "LangGraph worker orchestration."
            ),
            "capabilities": [
                "chat",
                "documentation_qa",
                "runtime_diagnostics",
                "multi_agent_supervision",
            ],
            "knowledge_sources": ["docker_docs"],
            "toolsets": ["docker_read_only"],
            "worker_roles": [
                "knowledge",
                "runtime",
                "diagnosis",
            ],
            "configuration_groups": [
                "model_settings",
                "retrieval_settings",
                "runtime_settings",
            ],
            "default_enabled": True,
        }
    ]


def test_agent_detail_api_normalizes_agent_type() -> None:
    client = TestClient(app)

    response = client.get("/agents/Docker-Support")

    assert response.status_code == 200
    assert response.json()["agent_type"] == "docker_support"


def test_agent_detail_api_returns_404_for_unregistered_type() -> None:
    client = TestClient(app)

    response = client.get("/agents/future_agent")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Agent type is not registered."
    )



def test_agent_detail_api_rejects_malformed_type() -> None:
    client = TestClient(app)

    response = client.get("/agents/bad%20agent")

    assert response.status_code == 400
    assert "agent_type may contain only" in response.json()["detail"]
