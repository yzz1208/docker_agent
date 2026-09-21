import pytest
from pydantic import ValidationError

from docker_agent.config import (
    Settings,
    get_settings,
    require_application_runtime_settings,
    settings_env_file,
)


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


def test_production_runtime_requires_model_identity() -> None:
    settings = _production_settings(model_name="")

    with pytest.raises(
        ValueError,
        match="MODEL_NAME",
    ):
        require_application_runtime_settings(settings)


def test_production_runtime_rejects_placeholder_values() -> None:
    settings = _production_settings(
        model_base_url="REPLACE_WITH_MODEL_BASE_URL"
    )

    with pytest.raises(
        ValueError,
        match="still contains a placeholder",
    ):
        require_application_runtime_settings(settings)


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


def test_get_settings_loads_environment_specific_dotenv(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env.test").write_text(
        "APP_ENV=test\n"
        "APP_NAME=Loaded From Test Env\n"
        "DATABASE_URL=sqlite+pysqlite:///:memory:\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()

    try:
        settings = get_settings()

        assert settings.app_env == "test"
        assert settings.app_name == "Loaded From Test Env"
        assert settings.database_url == "sqlite+pysqlite:///:memory:"
    finally:
        get_settings.cache_clear()



def test_non_production_runtime_does_not_require_model_configuration() -> None:
    settings = Settings(
        app_env="test",
        model_name="",
        model_base_url="",
    )

    require_application_runtime_settings(settings)
