from fastapi.testclient import TestClient

from docker_agent.main import app


def test_agents_api_lists_runtime_supported_agents() -> None:
    client = TestClient(app)

    response = client.get("/agents")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2

    descriptor = payload[0]
    infrastructure = payload[1]
    assert descriptor["agent_type"] == "docker_support"
    assert descriptor["display_name"] == "Docker Support"
    assert descriptor["capabilities"] == [
        "chat",
        "documentation_qa",
        "runtime_diagnostics",
        "multi_agent_supervision",
    ]
    assert descriptor["knowledge_sources"] == ["docker_docs"]
    assert descriptor["toolsets"] == ["docker_read_only"]
    assert descriptor["worker_roles"] == [
        "knowledge",
        "runtime",
        "diagnosis",
    ]
    assert descriptor["configuration_groups"] == [
        "model_settings",
        "retrieval_settings",
        "runtime_settings",
    ]
    assert [
        group["label"]
        for group in descriptor["configuration_schema"]
    ] == [
        "Model",
        "Retrieval",
        "Runtime",
    ]

    model_fields = descriptor["configuration_schema"][0]["fields"]
    temperature = next(
        field
        for field in model_fields
        if field["key"] == "temperature"
    )
    assert temperature == {
        "key": "temperature",
        "label": "Temperature",
        "description": "Sampling temperature for model responses.",
        "kind": "number",
        "minimum": 0.0,
        "maximum": 2.0,
    }

    assert descriptor["configuration_rules"] == [
        {
            "kind": "less_equal",
            "group": "retrieval_settings",
            "fields": ["rerank_top_k", "top_k"],
            "target_field": "rerank_top_k",
            "message": (
                "retrieval_settings.rerank_top_k must not exceed top_k"
            ),
        },
        {
            "kind": "not_all_zero",
            "group": "retrieval_settings",
            "fields": ["dense_weight", "keyword_weight"],
            "target_field": "keyword_weight",
            "message": (
                "retrieval dense_weight and keyword_weight cannot both "
                "be zero"
            ),
        },
    ]
    assert descriptor["default_enabled"] is True

    assert infrastructure["agent_type"] == (
        "infrastructure_troubleshooter"
    )
    assert infrastructure["display_name"] == (
        "Infrastructure Troubleshooter"
    )
    assert infrastructure["capabilities"] == [
        "chat",
        "incident_triage",
        "hypothesis_generation",
        "next_step_planning",
    ]
    assert infrastructure["knowledge_sources"] == [
        "embedded_incident_playbook"
    ]
    assert infrastructure["toolsets"] == []
    assert infrastructure["worker_roles"] == [
        "triage",
        "diagnosis",
    ]
    assert infrastructure["configuration_groups"] == [
        "model_settings",
        "runtime_settings",
    ]
    assert [
        group["label"]
        for group in infrastructure["configuration_schema"]
    ] == [
        "Model",
        "Triage",
    ]
    assert infrastructure["configuration_rules"] == []


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
