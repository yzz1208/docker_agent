from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.configuration_schema import (
    ConfigurationFieldDescriptor,
    ConfigurationGroupDescriptor,
)
from docker_agent.agent.registry import (
    DOCKER_SUPPORT_DESCRIPTOR,
    AgentDescriptor,
    AgentRegistry,
)
from docker_agent.main import app
from docker_agent.persistence import (
    create_agent_configuration,
    init_persistence_store,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def test_create_and_get_agent_configuration(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    created = client.post(
        "/agent-configurations",
        json={
            "agent_type": "docker_support",
            "display_name": "Docker Support",
            "enabled": True,
            "model_settings": {
                "model_name": "test-model",
                "temperature": 0.2,
                "max_tokens": 4096,
            },
            "retrieval_settings": {
                "top_k": 8,
                "rerank_top_k": 4,
            },
            "runtime_settings": {
                "max_steps": 5,
            },
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["agent_type"] == "docker_support"
    assert payload["display_name"] == "Docker Support"
    assert payload["enabled"] is True
    assert payload["model_settings"]["model_name"] == "test-model"
    assert payload["retrieval_settings"]["top_k"] == 8
    assert payload["runtime_settings"]["max_steps"] == 5
    assert "api_key" not in payload["model_settings"]

    loaded = client.get("/agent-configurations/docker_support")

    assert loaded.status_code == 200
    assert loaded.json() == payload


def test_registered_agent_configuration_uses_canonical_agent_type(
    monkeypatch,
) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.post(
        "/agent-configurations",
        json={
            "agent_type": "Docker-Support",
            "display_name": "Docker Support",
            "model_settings": {
                "temperature": 0.2,
            },
        },
    )

    assert response.status_code == 201
    assert response.json()["agent_type"] == "docker_support"

    loaded = client.get(
        "/agent-configurations/Docker-Support"
    )
    assert loaded.status_code == 200
    assert loaded.json()["agent_type"] == "docker_support"


def test_list_agent_configurations(monkeypatch) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="future_agent",
        display_name="Future Agent",
    )
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/agent-configurations")

    assert response.status_code == 200
    assert [item["agent_type"] for item in response.json()] == [
        "docker_support",
        "future_agent",
    ]


def test_registered_future_agent_uses_its_own_configuration_schema(
    monkeypatch,
) -> None:
    engine = _engine()
    registry = AgentRegistry(
        (
            DOCKER_SUPPORT_DESCRIPTOR,
            AgentDescriptor(
                agent_type="future_agent",
                display_name="Future Agent",
                description="Test-only configurable Agent.",
                capabilities=("chat",),
                knowledge_sources=(),
                toolsets=(),
                worker_roles=(),
                configuration_schema=(
                    ConfigurationGroupDescriptor(
                        key="model_settings",
                        label="Model",
                        fields=(
                            ConfigurationFieldDescriptor(
                                key="temperature",
                                settings_name="model_temperature",
                                label="Temperature",
                                description="Sampling temperature.",
                                kind="number",
                                minimum=0,
                                maximum=1,
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    monkeypatch.setattr(
        "docker_agent.main.agent_registry",
        registry,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    rejected = client.post(
        "/agent-configurations",
        json={
            "agent_type": "Future-Agent",
            "display_name": "Future Agent",
            "runtime_settings": {
                "max_steps": 4,
            },
        },
    )

    assert rejected.status_code == 400
    assert "runtime_settings is not supported" in (
        rejected.json()["detail"]
    )

    created = client.post(
        "/agent-configurations",
        json={
            "agent_type": "Future-Agent",
            "display_name": "Future Agent",
            "model_settings": {
                "temperature": 0.6,
            },
        },
    )

    assert created.status_code == 201
    assert created.json()["agent_type"] == "future_agent"
    assert created.json()["model_settings"] == {
        "temperature": 0.6,
    }

    effective = client.get(
        "/agent-configurations/future_agent/effective"
    )

    assert effective.status_code == 200
    payload = effective.json()
    assert payload["agent_type"] == "future_agent"
    assert payload["display_name"] == "Future Agent"
    assert payload["model_settings"]["temperature"][
        "persisted_value"
    ] == 0.6
    assert payload["model_settings"]["temperature"][
        "effective_value"
    ] == 0.6
    assert payload["retrieval_settings"] == {}
    assert payload["runtime_settings"] == {}


def test_patch_agent_configuration_is_partial(monkeypatch) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings={"temperature": 0.1},
        retrieval_settings={"top_k": 10},
        runtime_settings={"max_steps": 4},
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.patch(
        "/agent-configurations/docker_support",
        json={
            "display_name": "Docker Expert",
            "enabled": False,
            "runtime_settings": {
                "max_steps": 6,
                "tool_timeout_seconds": 10,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Docker Expert"
    assert payload["enabled"] is False
    assert payload["model_settings"] == {"temperature": 0.1}
    assert payload["retrieval_settings"] == {"top_k": 10}
    assert payload["runtime_settings"] == {
        "max_steps": 6,
        "tool_timeout_seconds": 10,
    }


def test_agent_configuration_api_rejects_secret_fields(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.post(
        "/agent-configurations",
        json={
            "agent_type": "docker_support",
            "display_name": "Docker Support",
            "model_settings": {
                "provider": {
                    "api_key": "must-not-be-stored",
                }
            },
        },
    )

    assert response.status_code == 400
    assert "api_key" in response.json()["detail"]
    assert "must not contain secret field" in response.json()["detail"]


def test_patch_agent_configuration_rejects_secret_fields_before_allowlist(
    monkeypatch,
) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings={"temperature": 0.1},
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.patch(
        "/agent-configurations/docker_support",
        json={
            "model_settings": {
                "provider": {
                    "api_key": "must-not-be-stored",
                }
            },
        },
    )

    assert response.status_code == 400
    assert "api_key" in response.json()["detail"]
    assert "must not contain secret field" in response.json()["detail"]

    loaded = client.get("/agent-configurations/docker_support")
    assert loaded.status_code == 200
    assert loaded.json()["model_settings"] == {"temperature": 0.1}


def test_duplicate_agent_configuration_returns_409(monkeypatch) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.post(
        "/agent-configurations",
        json={
            "agent_type": "docker_support",
            "display_name": "Duplicate",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Agent configuration already exists."
    )


def test_unknown_agent_configuration_returns_404(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    get_response = client.get("/agent-configurations/missing")
    patch_response = client.patch(
        "/agent-configurations/missing",
        json={"enabled": False},
    )

    assert get_response.status_code == 404
    assert get_response.json()["detail"] == (
        "Agent configuration was not found."
    )
    assert patch_response.status_code == 404
    assert patch_response.json()["detail"] == (
        "Agent configuration was not found."
    )


def test_agent_configuration_api_rejects_unsupported_runtime_fields(
    monkeypatch,
) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.post(
        "/agent-configurations",
        json={
            "agent_type": "docker_support",
            "display_name": "Docker Support",
            "model_settings": {
                "max_tokens": 4096,
                "token_budget": 12000,
            },
        },
    )

    assert response.status_code == 400
    assert "unsupported fields: token_budget" in response.json()["detail"]

    missing = client.get("/agent-configurations/docker_support")
    assert missing.status_code == 404


def test_patch_invalid_effective_config_does_not_persist(monkeypatch) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        retrieval_settings={
            "top_k": 10,
            "rerank_top_k": 5,
        },
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.patch(
        "/agent-configurations/docker_support",
        json={
            "retrieval_settings": {
                "top_k": 3,
                "rerank_top_k": 5,
            }
        },
    )

    assert response.status_code == 400
    assert "rerank_top_k must not exceed top_k" in response.json()["detail"]

    loaded = client.get("/agent-configurations/docker_support")
    assert loaded.status_code == 200
    assert loaded.json()["retrieval_settings"] == {
        "top_k": 10,
        "rerank_top_k": 5,
    }
