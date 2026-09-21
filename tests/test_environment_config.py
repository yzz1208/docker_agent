import pytest
from pydantic import ValidationError

from docker_agent.config import Settings, settings_env_file


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": (
            "postgresql+psycopg://docker_agent:"
            "strong-random-password@postgres:5432/docker_agent"
        ),
        "model_name": "production-model",
        "model_base_url": "https://model.example/v1",
        "tool_mode": "mock",
    }
    values.update(overrides)
    return Settings(**values)


def test_environment_file_mapping_is_explicit() -> None:
    assert settings_env_file("development") == ".env"
    assert settings_env_file("test") == ".env.test"
    assert settings_env_file("production") == ".env.production"


def test_settings_normalize_log_level() -> None:
    settings = Settings(app_log_level="warning")

    assert settings.app_log_level == "WARNING"


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="staging")


def test_production_settings_accept_safe_configuration() -> None:
    settings = _production_settings()

    assert settings.app_env == "production"
    assert settings.tool_mode == "mock"


def test_production_rejects_default_postgres_password() -> None:
    with pytest.raises(
        ValidationError,
        match="non-default password",
    ):
        _production_settings(
            database_url=(
                "postgresql+psycopg://postgres:"
                "postgres@postgres:5432/docker_agent"
            )
        )


def test_production_rejects_sqlite_database() -> None:
    with pytest.raises(
        ValidationError,
        match="must use PostgreSQL",
    ):
        _production_settings(
            database_url="sqlite+pysqlite:///:memory:"
        )


def test_production_requires_model_identity() -> None:
    with pytest.raises(
        ValidationError,
        match="MODEL_NAME",
    ):
        _production_settings(model_name="")


def test_production_rejects_placeholder_values() -> None:
    with pytest.raises(
        ValidationError,
        match="still contains a placeholder",
    ):
        _production_settings(
            model_base_url="REPLACE_WITH_MODEL_BASE_URL"
        )


def test_production_local_docker_requires_explicit_opt_in() -> None:
    with pytest.raises(
        ValidationError,
        match="ALLOW_LOCAL_DOCKER_TOOLS=true",
    ):
        _production_settings(tool_mode="local")


def test_production_local_docker_can_be_explicitly_enabled() -> None:
    settings = _production_settings(
        tool_mode="local",
        allow_local_docker_tools=True,
    )

    assert settings.tool_mode == "local"
    assert settings.allow_local_docker_tools is True
