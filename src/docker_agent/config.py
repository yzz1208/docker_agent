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

    tool_mode: str = "mock"
    docker_tool_timeout_seconds: float = 15.0
    docker_logs_max_lines: int = 200
    runtime_evidence_max_chars: int = 8_000
    dynamic_runtime_max_steps: int = 4

    retrieval_top_k: int = 10
    retrieval_candidate_k: int = 20
    retrieval_rrf_k: int = 60
    retrieval_dense_weight: float = 1.0
    retrieval_keyword_weight: float = 1.0
    rerank_top_k: int = 5
    rag_context_max_chars: int = 14_000

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
