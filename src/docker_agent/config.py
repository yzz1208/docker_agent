from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "Docker Support Agent"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent"
    )

    model_provider: str = ""
    model_name: str = ""
    model_api_key: str = ""
    model_base_url: str = ""

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
