from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from docker_agent.persistence import (
    AgentConfigurationAlreadyExists,
    AgentConfigurationNotFound,
    create_agent_configuration,
    get_agent_configuration,
    init_persistence_store,
    list_agent_configurations,
    update_agent_configuration,
)


def _engine() -> Engine:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def test_agent_configuration_round_trip() -> None:
    engine = _engine()

    created = create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings={
            "model_name": "test-model",
            "temperature": 0.2,
            "max_tokens": 2048,
        },
        retrieval_settings={
            "top_k": 8,
            "rerank_top_k": 4,
        },
        runtime_settings={
            "max_steps": 5,
            "tool_timeout_seconds": 12.0,
        },
    )
    loaded = get_agent_configuration(engine, "docker_support")

    assert loaded == created
    assert loaded.enabled is True
    assert loaded.model_settings["model_name"] == "test-model"
    assert loaded.model_settings["max_tokens"] == 2048
    assert loaded.retrieval_settings["top_k"] == 8
    assert loaded.runtime_settings["max_steps"] == 5


def test_list_agent_configurations_orders_by_display_name() -> None:
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

    records = list_agent_configurations(engine)

    assert [record.agent_type for record in records] == [
        "docker_support",
        "future_agent",
    ]


def test_update_agent_configuration_changes_only_supplied_fields() -> None:
    engine = _engine()
    created = create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings={"temperature": 0.1},
        retrieval_settings={"top_k": 10},
        runtime_settings={"max_steps": 4},
    )

    updated = update_agent_configuration(
        engine,
        "docker_support",
        display_name="Docker Expert",
        enabled=False,
        runtime_settings={"max_steps": 6},
    )

    assert updated.display_name == "Docker Expert"
    assert updated.enabled is False
    assert updated.model_settings == {"temperature": 0.1}
    assert updated.retrieval_settings == {"top_k": 10}
    assert updated.runtime_settings == {"max_steps": 6}
    assert updated.updated_at >= created.updated_at


def test_agent_configuration_rejects_nested_secret_fields() -> None:
    engine = _engine()

    try:
        create_agent_configuration(
            engine,
            agent_type="docker_support",
            display_name="Docker Support",
            model_settings={
                "provider": {
                    "api_key": "should-not-be-stored",
                }
            },
        )
    except ValueError as exc:
        assert "api_key" in str(exc)
        assert "must not contain secret field" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")


def test_agent_configuration_allows_non_secret_token_settings() -> None:
    engine = _engine()

    record = create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings={
            "max_tokens": 4096,
            "token_budget": 12000,
        },
    )

    assert record.model_settings["max_tokens"] == 4096
    assert record.model_settings["token_budget"] == 12000


def test_agent_configuration_copies_input_settings() -> None:
    engine = _engine()
    settings: dict[str, object] = {
        "nested": {
            "temperature": 0.1,
        }
    }

    record = create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
        model_settings=settings,
    )

    nested = settings["nested"]
    assert isinstance(nested, dict)
    nested["temperature"] = 0.9

    assert record.model_settings == {
        "nested": {
            "temperature": 0.1,
        }
    }
    loaded = get_agent_configuration(engine, "docker_support")
    assert loaded.model_settings == {
        "nested": {
            "temperature": 0.1,
        }
    }


def test_duplicate_agent_configuration_is_rejected() -> None:
    engine = _engine()
    create_agent_configuration(
        engine,
        agent_type="docker_support",
        display_name="Docker Support",
    )

    try:
        create_agent_configuration(
            engine,
            agent_type="docker_support",
            display_name="Duplicate",
        )
    except AgentConfigurationAlreadyExists as exc:
        assert exc.args == ("docker_support",)
    else:
        raise AssertionError("AgentConfigurationAlreadyExists was not raised")


def test_unknown_agent_configuration_is_rejected() -> None:
    engine = _engine()

    try:
        get_agent_configuration(engine, "missing")
    except AgentConfigurationNotFound as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("AgentConfigurationNotFound was not raised")
