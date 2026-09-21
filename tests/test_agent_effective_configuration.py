from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.agent.configuration import (
    AgentConfigurationResolutionError,
    AgentDisabledError,
    require_enabled,
    resolve_docker_support_configuration,
    resolve_docker_support_settings,
)
from docker_agent.config import Settings
from docker_agent.main import get_agent
from docker_agent.persistence import (
    AgentConfigurationRecord,
    create_agent_configuration,
    init_persistence_store,
)


def _record(
    *,
    enabled: bool = True,
    model_settings: dict[str, object] | None = None,
    retrieval_settings: dict[str, object] | None = None,
    runtime_settings: dict[str, object] | None = None,
) -> AgentConfigurationRecord:
    now = datetime.now(UTC)
    return AgentConfigurationRecord(
        agent_type="docker_support",
        display_name="Docker Expert",
        enabled=enabled,
        model_settings=model_settings or {},
        retrieval_settings=retrieval_settings or {},
        runtime_settings=runtime_settings or {},
        created_at=now,
        updated_at=now,
    )


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def test_resolver_preserves_secure_environment_values() -> None:
    base = Settings(
        database_url="postgresql+psycopg://secure-db",
        model_base_url="https://secure.example/v1",
        model_api_key="secure-key",
        model_name="env-model",
    )
    config = resolve_docker_support_configuration(
        base,
        _record(
            model_settings={
                "model_name": "ui-model",
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            runtime_settings={
                "max_steps": 6,
            },
        ),
    )

    assert config.persisted is True
    assert config.display_name == "Docker Expert"
    assert config.settings.model_name == "ui-model"
    assert config.settings.model_temperature == 0.3
    assert config.settings.model_max_tokens == 2048
    assert config.settings.dynamic_runtime_max_steps == 6
    assert config.settings.model_base_url == "https://secure.example/v1"
    assert config.settings.model_api_key == "secure-key"
    assert config.settings.database_url == "postgresql+psycopg://secure-db"


def test_resolver_applies_retrieval_and_runtime_preferences() -> None:
    base = Settings(
        model_name="env-model",
        model_base_url="https://example.test/v1",
    )

    settings = resolve_docker_support_settings(
        base,
        model_settings={},
        retrieval_settings={
            "top_k": 12,
            "rrf_k": 80,
            "dense_weight": 1.5,
            "keyword_weight": 0.5,
            "rerank_top_k": 6,
            "context_max_chars": 18000,
        },
        runtime_settings={
            "max_steps": 7,
            "tool_timeout_seconds": 9.5,
            "logs_max_lines": 300,
            "evidence_max_chars": 10000,
        },
    )

    assert settings.retrieval_candidate_k == 12
    assert settings.retrieval_rrf_k == 80
    assert settings.retrieval_dense_weight == 1.5
    assert settings.retrieval_keyword_weight == 0.5
    assert settings.rerank_top_k == 6
    assert settings.rag_context_max_chars == 18000
    assert settings.dynamic_runtime_max_steps == 7
    assert settings.docker_tool_timeout_seconds == 9.5
    assert settings.docker_logs_max_lines == 300
    assert settings.runtime_evidence_max_chars == 10000


def test_resolver_rejects_unsupported_product_fields() -> None:
    with pytest.raises(
        AgentConfigurationResolutionError,
        match="unsupported fields: token_budget",
    ):
        resolve_docker_support_settings(
            Settings(),
            model_settings={"token_budget": 12000},
            retrieval_settings={},
            runtime_settings={},
        )


def test_resolver_rejects_invalid_rerank_pool() -> None:
    with pytest.raises(
        AgentConfigurationResolutionError,
        match="rerank_top_k must not exceed top_k",
    ):
        resolve_docker_support_settings(
            Settings(),
            model_settings={},
            retrieval_settings={
                "top_k": 3,
                "rerank_top_k": 5,
            },
            runtime_settings={},
        )


def test_require_enabled_blocks_disabled_agent() -> None:
    config = resolve_docker_support_configuration(
        Settings(),
        _record(enabled=False),
    )

    with pytest.raises(AgentDisabledError, match="docker_support"):
        require_enabled(config)


def test_get_agent_uses_persisted_preferences_without_overriding_secrets(
    monkeypatch,
) -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Expert",
        model_settings={
            "model_name": "ui-model",
            "temperature": 0.4,
            "max_tokens": 1536,
        },
        runtime_settings={
            "max_steps": 6,
            "tool_timeout_seconds": 7.0,
        },
    )
    base = Settings(
        model_name="env-model",
        model_base_url="https://secure.example/v1",
        model_api_key="secure-key",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    monkeypatch.setattr(
        "docker_agent.main.get_settings",
        lambda: base,
    )
    get_agent.cache_clear()

    try:
        agent = get_agent()
    finally:
        get_agent.cache_clear()

    assert agent.settings.model_name == "ui-model"
    assert agent.settings.model_temperature == 0.4
    assert agent.settings.model_max_tokens == 1536
    assert agent.settings.model_base_url == "https://secure.example/v1"
    assert agent.settings.model_api_key == "secure-key"
    assert agent.settings.dynamic_runtime_max_steps == 6
    assert agent.docker_tools.timeout_seconds == 7.0
