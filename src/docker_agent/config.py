from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Local development defaults to SQLite so the project can run before
    Docker/PostgreSQL is installed. Later milestones can switch DATABASE_URL
    to PostgreSQL + pgvector without changing application code.
    """

    app_name: str = "Docker Support Agent"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = "sqlite:///./docker_agent.db"

    model_provider: str = ""
    model_name: str = ""
    model_api_key: str = ""
    model_base_url: str = ""

    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    tool_mode: str = "mock"
    retrieval_top_k: int = 10
    rerank_top_k: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance for dependency injection."""

    return Settings()
