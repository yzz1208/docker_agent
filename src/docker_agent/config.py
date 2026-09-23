from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

AppEnvironment = Literal["development", "test", "production"]
ToolMode = Literal["mock", "local"]

_ENV_FILES: dict[str, str] = {
    "development": ".env",
    "test": ".env.test",
    "production": ".env.production",
}

_UNSAFE_PRODUCTION_PASSWORDS = {
    "",
    "postgres",
    "password",
    "changeme",
    "change-me",
    "secret",
    "replace_with_strong_random_password",
}


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "Docker Support Agent"
    app_env: AppEnvironment = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_log_level: str = "INFO"

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent"
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=0)
    database_migration_config: str = "alembic.ini"

    model_provider: str = ""
    model_name: str = ""
    model_api_key: str = ""
    model_base_url: str = ""
    model_timeout_seconds: float = 60.0
    model_temperature: float = 0.1
    model_max_tokens: int | None = None
    model_max_retries: int = 2
    model_retry_backoff_seconds: float = 0.5

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = ""
    embedding_cache_dir: str = ""
    embedding_batch_size: int = 8
    embedding_dimension: int = 1024

    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = ""
    rerank_cache_dir: str = ""
    rerank_batch_size: int = 4
    rerank_max_length: int = 512
    rerank_use_fp16: bool = True

    tool_mode: ToolMode = "mock"
    allow_local_docker_tools: bool = False
    docker_tool_timeout_seconds: float = 15.0
    docker_logs_max_lines: int = 200
    runtime_evidence_max_chars: int = 8_000
    dynamic_runtime_max_steps: int = 4

    incident_max_hypotheses: int = Field(default=3, ge=1, le=10)
    incident_max_next_steps: int = Field(default=5, ge=1, le=20)

    conversation_context_max_messages: int = Field(default=12, ge=0, le=100)
    conversation_context_max_chars: int = Field(default=6000, ge=0, le=50000)

    retrieval_top_k: int = 10
    retrieval_candidate_k: int = 20
    retrieval_rrf_k: int = 60
    retrieval_dense_weight: float = 1.0
    retrieval_keyword_weight: float = 1.0
    rerank_top_k: int = 5
    rag_context_max_chars: int = 14_000

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("app_log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized not in {
                "DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            }:
                raise ValueError("APP_LOG_LEVEL is not supported")
            return normalized
        return value

    @model_validator(mode="after")
    def validate_environment_contract(self) -> Self:
        if self.app_env != "production":
            return self

        try:
            database = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError(
                "Production DATABASE_URL is invalid"
            ) from exc
        if database.get_backend_name() != "postgresql":
            raise ValueError(
                "Production DATABASE_URL must use PostgreSQL"
            )

        password = database.password or ""
        if password.strip().lower() in _UNSAFE_PRODUCTION_PASSWORDS:
            raise ValueError(
                "Production DATABASE_URL must use a non-default password"
            )

        if "REPLACE_WITH_" in self.database_url.upper():
            raise ValueError(
                "Production DATABASE_URL still contains a placeholder"
            )

        if (
            self.tool_mode == "local"
            and not self.allow_local_docker_tools
        ):
            raise ValueError(
                "Production TOOL_MODE=local requires "
                "ALLOW_LOCAL_DOCKER_TOOLS=true"
            )

        return self


def require_application_runtime_settings(settings: Settings) -> None:
    """Require configuration needed by the serving Agent runtime."""

    if settings.app_env != "production":
        return

    if not settings.model_name.strip():
        raise ValueError("Production MODEL_NAME must be configured")
    if not settings.model_base_url.strip():
        raise ValueError(
            "Production MODEL_BASE_URL must be configured"
        )

    for label, value in {
        "MODEL_NAME": settings.model_name,
        "MODEL_BASE_URL": settings.model_base_url,
        "MODEL_API_KEY": settings.model_api_key,
    }.items():
        if value and "REPLACE_WITH_" in value.upper():
            raise ValueError(
                f"Production {label} still contains a placeholder"
            )


def settings_env_file(app_env: str | None = None) -> str:
    """Return the dotenv file associated with one application environment."""

    normalized = (
        app_env
        if app_env is not None
        else os.getenv("APP_ENV", "development")
    ).strip().lower()
    return _ENV_FILES.get(normalized, ".env")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings using the environment-specific dotenv file."""

    return Settings(_env_file=settings_env_file())
