from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.config import Settings
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


def test_effective_configuration_reports_environment_and_defaults(
    monkeypatch,
) -> None:
    engine = _engine()
    base = Settings(
        model_name="env-model",
        model_api_key="super-secret-key",
        model_base_url="https://secure.example/v1",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_settings",
        lambda: base,
    )
    client = TestClient(app)

    response = client.get(
        "/agent-configurations/docker_support/effective"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "docker_support"
    assert payload["display_name"] == "Docker Support"
    assert payload["enabled"] is True
    assert payload["persisted"] is False
    assert payload["configuration_updated_at"] is None

    model_name = payload["model_settings"]["model_name"]
    assert model_name == {
        "persisted_value": None,
        "base_value": "env-model",
        "effective_value": "env-model",
        "source": "environment",
        "editable": True,
        "secure": False,
        "configured": True,
    }

    top_k = payload["retrieval_settings"]["top_k"]
    assert top_k["persisted_value"] is None
    assert top_k["base_value"] == base.retrieval_candidate_k
    assert top_k["effective_value"] == base.retrieval_candidate_k
    assert top_k["source"] == "default"
    assert top_k["editable"] is True
    assert top_k["secure"] is False

    api_key = payload["environment_settings"]["model_api_key"]
    assert api_key["persisted_value"] is None
    assert api_key["base_value"] is None
    assert api_key["effective_value"] is None
    assert api_key["source"] == "environment"
    assert api_key["editable"] is False
    assert api_key["secure"] is True
    assert api_key["configured"] is True

    base_url = payload["environment_settings"]["model_base_url"]
    assert base_url["base_value"] is None
    assert base_url["effective_value"] is None
    assert base_url["secure"] is True
    assert base_url["configured"] is True

    assert "super-secret-key" not in response.text
    assert "https://secure.example/v1" not in response.text
    assert base.database_url not in response.text


def test_effective_configuration_shows_persisted_overrides(
    monkeypatch,
) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Expert",
        enabled=False,
        model_settings={
            "model_name": "ui-model",
            "temperature": 0.35,
        },
        retrieval_settings={
            "top_k": 12,
            "rerank_top_k": 6,
        },
        runtime_settings={
            "max_steps": 7,
        },
    )
    base = Settings(
        model_name="env-model",
        model_temperature=0.1,
        retrieval_candidate_k=20,
        rerank_top_k=5,
        dynamic_runtime_max_steps=4,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_settings",
        lambda: base,
    )
    client = TestClient(app)

    response = client.get(
        "/agent-configurations/docker_support/effective"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Docker Expert"
    assert payload["enabled"] is False
    assert payload["persisted"] is True
    assert payload["configuration_updated_at"] is not None

    model_name = payload["model_settings"]["model_name"]
    assert model_name["persisted_value"] == "ui-model"
    assert model_name["base_value"] == "env-model"
    assert model_name["effective_value"] == "ui-model"
    assert model_name["source"] == "persisted"

    temperature = payload["model_settings"]["temperature"]
    assert temperature["persisted_value"] == 0.35
    assert temperature["base_value"] == 0.1
    assert temperature["effective_value"] == 0.35
    assert temperature["source"] == "persisted"

    top_k = payload["retrieval_settings"]["top_k"]
    assert top_k["persisted_value"] == 12
    assert top_k["base_value"] == 20
    assert top_k["effective_value"] == 12
    assert top_k["source"] == "persisted"

    max_steps = payload["runtime_settings"]["max_steps"]
    assert max_steps["persisted_value"] == 7
    assert max_steps["base_value"] == 4
    assert max_steps["effective_value"] == 7
    assert max_steps["source"] == "persisted"


def test_effective_configuration_marks_visible_environment_owned_fields(
    monkeypatch,
) -> None:
    engine = _engine()
    base = Settings(
        model_provider="openai-compatible",
        embedding_model="test-embedding",
        rerank_model="test-reranker",
        tool_mode="local",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_settings",
        lambda: base,
    )
    client = TestClient(app)

    response = client.get(
        "/agent-configurations/docker_support/effective"
    )

    assert response.status_code == 200
    environment = response.json()["environment_settings"]

    assert environment["model_provider"]["effective_value"] == (
        "openai-compatible"
    )
    assert environment["model_provider"]["source"] == "environment"
    assert environment["model_provider"]["editable"] is False
    assert environment["model_provider"]["secure"] is False
    assert environment["embedding_model"]["effective_value"] == (
        "test-embedding"
    )
    assert environment["rerank_model"]["effective_value"] == (
        "test-reranker"
    )
    assert environment["tool_mode"]["effective_value"] == "local"


def test_effective_configuration_rejects_unsupported_agent_type(
    monkeypatch,
) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/agent-configurations/future_agent/effective"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Effective configuration is not supported for agent type "
        "'future_agent'."
    )
